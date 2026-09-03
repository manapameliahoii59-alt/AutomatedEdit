"""常读平台 API 客户端（Playwright 注入 secsdk 签名 + requests 下载 zip）。"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import requests
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from app.data.services.changdu_browser import (
    LAUNCH_ARGS,
    STEALTH_INIT_SCRIPT,
    browser_context_kwargs,
    format_cookie_header,
    zip_download_headers,
)
from app.data.services.changdu_paths import AUTH_FILE, DEFAULT_DOWNLOAD_DIR

SERIES_LIST_PATH = "/novelsale/distributor/content/series/list/v1/"
EPISODE_INFO_PATH = "/novelsale/distributor/content/episode/info/v1"
PLAYER_INFO_PATH = "/novelsale/distributor/content/player/info/v2/"
BATCH_DOWNLOAD_PATH = "/node/api/platform/distributor/playlet/batch_create_download_task/v6/"
DOWNLOAD_TASK_LIST_PATH = "/node/api/platform/distributor/download_center/task_list/"
DOWNLOAD_GET_URL_PATH = "/node/api/platform/distributor/download_center/get_url/"

DOWNLOAD_TASK_STATUS_DONE = 2

HOME_URL = "https://www.changdupingtai.com/page/home?show=true"
SHORT_PLAY_LIST_URL = "https://www.changdupingtai.com/sale/short-play/list"
SHORT_PLAY_LIST_REFERER = SHORT_PLAY_LIST_URL
GOTO_RETRIES = 3
GOTO_TIMEOUT_MS = 90_000
SECSdk_READY_TIMEOUT_MS = 30_000


def _format_playwright_network_error(exc: BaseException) -> RuntimeError:
    msg = str(exc)
    if any(
        token in msg
        for token in ("ERR_CONNECTION", "TIMED_OUT", "net::", "NS_ERROR", "ECONNREFUSED")
    ):
        return RuntimeError(
            "无法连接常读平台（网络超时）。请检查网络或代理后重试，"
            "也可在浏览器中手动打开 changdupingtai.com 确认能否访问。"
        )
    return RuntimeError(msg)


class SeriesListClient:
    def __init__(
        self,
        *,
        auth_file: Path | str | None = None,
        app_type: int = 21,
        headless: bool = True,
    ):
        self.auth_file = Path(auth_file or AUTH_FILE)
        self.app_type = app_type
        self.headless = headless
        self._playwright = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None
        self.ad_user_id: str | None = None
        self.root_ad_user_id: str | None = None
        self.app_info: dict[str, Any] | None = None
        self._cookie_header: str = ""
        self._owner_thread_id: int | None = None
        self._closed = False

    def _assert_playwright_thread(self) -> None:
        owner = self._owner_thread_id
        if owner is not None and threading.get_ident() != owner:
            raise RuntimeError(
                "SeriesListClient 的浏览器 API 只能在 PlaywrightWorker 线程中调用"
            )
        if self._closed:
            raise RuntimeError("SeriesListClient 已关闭")

    def init(self) -> SeriesListClient:
        if not self.auth_file.is_file():
            raise FileNotFoundError(
                f"未找到 {self.auth_file}，请先在「视频下载」页登录常读平台"
            )

        self._owner_thread_id = threading.get_ident()
        self._closed = False
        try:
            self._playwright = sync_playwright().start()
            self.browser = self._playwright.chromium.launch(
                headless=self.headless,
                args=list(LAUNCH_ARGS),
            )
            self.context = self.browser.new_context(
                **browser_context_kwargs(storage_state=str(self.auth_file))
            )
            self.page = self.context.new_page()
            self.page.add_init_script(STEALTH_INIT_SCRIPT)

            cookies = self.context.cookies()
            self._cookie_header = format_cookie_header(cookies)
            self.ad_user_id = next((c["value"] for c in cookies if c["name"] == "adUserId"), None)
            self.root_ad_user_id = next(
                (c["value"] for c in cookies if c["name"] == "rootAdUserId"), None
            )
            if not self.ad_user_id:
                raise RuntimeError("auth.json 中缺少 adUserId Cookie，请重新登录")
            if not self.root_ad_user_id:
                raise RuntimeError("auth.json 中缺少 rootAdUserId Cookie，请重新登录")

            self._goto_home_page()
            self._wait_for_secsdk_ready()
            self.app_info = self._resolve_app_info()
            self._goto_short_play_list()
            return self
        except Exception as exc:
            self.close()
            if isinstance(exc, RuntimeError):
                raise
            raise _format_playwright_network_error(exc) from exc

    def _goto_home_page(self) -> None:
        self._assert_playwright_thread()
        assert self.page
        last_err: BaseException | None = None
        for attempt in range(1, GOTO_RETRIES + 1):
            try:
                self.page.goto(
                    HOME_URL,
                    timeout=GOTO_TIMEOUT_MS,
                    wait_until="load",
                )
                return
            except Exception as exc:
                last_err = exc
                if attempt < GOTO_RETRIES:
                    time.sleep(3)
        if last_err is not None:
            raise _format_playwright_network_error(last_err) from last_err
        raise RuntimeError("常读平台首页加载失败")

    def _wait_for_secsdk_ready(self) -> None:
        """等待首页 secsdk 完成 fetch 劫持（content API 依赖签名）。"""
        self._assert_playwright_thread()
        assert self.page
        try:
            self.page.wait_for_function(
                "() => typeof window.use === 'function'",
                timeout=SECSdk_READY_TIMEOUT_MS,
            )
            self.page.wait_for_timeout(3500)
        except Exception:
            # 弱网或页面结构变化时退化为固定等待
            self.page.wait_for_timeout(5000)

    def _goto_short_play_list(self) -> None:
        """进入短剧列表页，确保 content/series 等 API 的 secsdk 签名上下文就绪。"""
        self._assert_playwright_thread()
        assert self.page
        list_params = {
            "sort_type": "1",
            **self._default_series_date_range(),
            "sort_field": "8",
            "aweme_user_new_version": "true",
            "page_index": "1",
            "page_size": "10",
        }
        from urllib.parse import urlencode

        self.page.goto(
            f"{SHORT_PLAY_LIST_URL}?{urlencode(list_params)}",
            timeout=GOTO_TIMEOUT_MS,
            wait_until="load",
        )
        self.page.wait_for_timeout(2000)

    @staticmethod
    def _default_series_date_range(days: int = 30) -> dict[str, str]:
        """与常读列表页一致：含首尾共 days 天（如 30 → 6/17～7/16）。"""
        end = datetime.now()
        # timedelta(days=30) 会得到 31 个自然日，触发「超过最大查询天数」
        start = end - timedelta(days=max(days - 1, 0))
        return {
            "start_time": start.strftime("%Y-%m-%d"),
            "end_time": end.strftime("%Y-%m-%d"),
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.page = None
        self.context = None
        browser = self.browser
        self.browser = None
        pw = self._playwright
        self._playwright = None
        self._owner_thread_id = None
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if pw:
            try:
                pw.stop()
            except Exception:
                pass

    def __enter__(self) -> SeriesListClient:
        return self.init()

    def __exit__(self, *args: object) -> None:
        self.close()

    def _resolve_app_info(self) -> dict[str, Any]:
        self._assert_playwright_thread()
        assert self.page and self.ad_user_id
        pkg_json = self.page.evaluate(
            """async (uid) => {
                const res = await fetch('/novelsale/distributor/get_available_packages/v2/?', {
                    credentials: 'include',
                    headers: {
                        accept: 'application/json, text/plain, */*',
                        appid: '0',
                        apptype: '1',
                        distributorid: '0',
                        aduserid: uid,
                        'agw-js-conv': 'str',
                        'x-secsdk-csrf-token': 'DOWNGRADE',
                    },
                });
                return res.json();
            }""",
            self.ad_user_id,
        )
        app = (pkg_json.get("available_packages") or {}).get(str(self.app_type), [None])[0]
        if not app:
            raise RuntimeError(f"未找到 appType={self.app_type} 的应用配置，请检查账号权限")
        return {
            "app_id": app["app_id"],
            "app_type": app["app_type"],
            "distributor_id": app["distributor_id"],
            "app_name": app["app_name"],
            "distributor_name": app["distributor_name"],
        }

    def _request_context(self) -> dict[str, Any]:
        if not self.page or not self.app_info:
            raise RuntimeError("请先调用 init()")
        return {
            "app": self.app_info,
            "adUserId": self.ad_user_id,
            "rootAdUserId": self.root_ad_user_id,
        }

    @staticmethod
    def _default_unix_time_range(days: int = 30) -> dict[str, str]:
        end = int(time.time())
        start = end - days * 24 * 3600
        return {"start_time": str(start), "end_time": str(end)}

    def _api_fetch(
        self,
        api_path: str,
        params: dict[str, Any],
        *,
        platform: bool = False,
        referer: str | None = None,
        content_api: bool = False,
    ) -> dict[str, Any]:
        self._assert_playwright_thread()
        ctx = self._request_context()
        referer = referer or "https://www.changdupingtai.com/sale/download-center"
        assert self.page

        result = self.page.evaluate(
            """async ({ apiPath, params, app, adUserId, rootAdUserId, platform, referer, contentApi }) => {
                const qs = new URLSearchParams(params).toString();
                const headers = {
                    accept: 'application/json, text/plain, */*',
                    appid: String(app.app_id),
                    apptype: String(app.app_type),
                    distributorid: String(app.distributor_id),
                    aduserid: adUserId,
                    'agw-js-conv': 'str',
                };
                if (!contentApi) {
                    headers['x-secsdk-csrf-token'] = 'DOWNGRADE';
                }
                if (platform) {
                    headers.rootaduserid = rootAdUserId;
                }
                if (referer && !contentApi) {
                    headers.referer = referer;
                }
                const res = await fetch(`${apiPath}?${qs}`, {
                    method: 'GET',
                    credentials: 'include',
                    headers,
                });
                const text = await res.text();
                let json = null;
                let parseError = null;
                if (text) {
                    try { json = JSON.parse(text); } catch (e) { parseError = e.message; }
                } else {
                    parseError = 'empty body';
                }
                return { status: res.status, text: text.slice(0, 500), json, parseError };
            }""",
            {
                "apiPath": api_path,
                "params": {k: str(v) for k, v in params.items()},
                **ctx,
                "platform": platform,
                "referer": referer,
                "contentApi": content_api,
            },
        )
        return self._parse_api_result(api_path, result)

    def _api_post(self, api_path: str, body: dict[str, Any], *, referer: str | None = None) -> dict[str, Any]:
        self._assert_playwright_thread()
        ctx = self._request_context()
        body_str = json.dumps(body)
        referer = referer or (
            f"https://www.changdupingtai.com/sale/short-play/list/detail?id={body.get('book_id')}&contentGenre=2"
            if body.get("book_id")
            else "https://www.changdupingtai.com/sale/short-play/list"
        )
        assert self.page

        result = self.page.evaluate(
            """async ({ apiPath, bodyStr, app, adUserId, rootAdUserId, referer }) => {
                const res = await fetch(apiPath, {
                    method: 'POST',
                    credentials: 'include',
                    headers: {
                        accept: 'application/json, text/plain, */*',
                        'content-type': 'application/json',
                        appid: String(app.app_id),
                        apptype: String(app.app_type),
                        distributorid: String(app.distributor_id),
                        aduserid: adUserId,
                        rootaduserid: rootAdUserId,
                        'agw-js-conv': 'str',
                        'x-secsdk-csrf-token': 'DOWNGRADE',
                        referer,
                    },
                    body: bodyStr,
                });
                const text = await res.text();
                let json = null;
                let parseError = null;
                if (text) {
                    try { json = JSON.parse(text); } catch (e) { parseError = e.message; }
                } else {
                    parseError = 'empty body';
                }
                return { status: res.status, text: text.slice(0, 500), json, parseError };
            }""",
            {"apiPath": api_path, "bodyStr": body_str, **ctx, "referer": referer},
        )
        return self._parse_api_result(api_path, result)

    def _format_api_error(self, api_path: str, result: dict[str, Any]) -> str:
        body = result.get("text") or ""
        status = result.get("status", 0)
        login_hint = ""
        if status in (401, 403) or re.search(r"login|passport|未登录|请登录", body, re.I):
            login_hint = "（登录可能已过期，请重新登录常读平台）"
        detail = json.dumps(result.get("json"), ensure_ascii=False) if result.get("json") else body[:200]
        if not detail:
            detail = result.get("parseError") or ""
        if detail == "empty body":
            detail = (
                "empty body（接口无返回内容，多为 secsdk 签名未就绪或登录态失效，"
                "请重新登录常读平台后重试）"
            )
        return f"HTTP {status} {api_path}: {detail}{login_hint}"

    def _parse_api_result(self, api_path: str, result: dict[str, Any]) -> dict[str, Any]:
        if result.get("parseError"):
            raise RuntimeError(self._format_api_error(api_path, result))
        if result.get("status") != 200:
            raise RuntimeError(self._format_api_error(api_path, result))
        return result["json"]

    def fetch_list(self, query: dict[str, Any] | None = None) -> dict[str, Any]:
        defaults = {
            "sort_type": "1",
            **self._default_series_date_range(),
            "sort_field": "8",
            "aweme_user_new_version": "true",
            "page_index": "0",
            "page_size": "10",
        }
        return self._api_fetch(
            SERIES_LIST_PATH,
            {**defaults, **(query or {})},
            referer=SHORT_PLAY_LIST_REFERER,
            content_api=True,
        )

    def fetch_episode_info(self, book_id: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        params = {
            "book_id": str(book_id),
            "aweme_user_new_version": "true",
            "page_index": "0",
            "page_size": "50",
            **(options or {}),
        }
        return self._api_fetch(
            EPISODE_INFO_PATH,
            params,
            referer=SHORT_PLAY_LIST_REFERER,
        )

    def fetch_episodes_in_range(self, book_id: str, from_ep: int, to_ep: int) -> dict[str, Any]:
        if from_ep < 1 or to_ep < from_ep:
            raise ValueError(f"无效集数范围: {from_ep}-{to_ep}")
        # 拉取至 to_ep，再由调用方按 from_ep 切片（page 从第 1 集起算）
        return self.fetch_episode_info(
            book_id,
            {"page_index": "0", "page_size": str(to_ep)},
        )

    def create_batch_download_task(
        self,
        *,
        book_id: str,
        book_name: str,
        item_ids: list[str],
        from_ep: int,
        to_ep: int,
    ) -> dict[str, Any]:
        if not item_ids:
            raise ValueError("item_ids 不能为空")
        if to_ep - from_ep + 1 != len(item_ids):
            raise ValueError(
                f"item_ids 数量({len(item_ids)})与集数范围({from_ep}-{to_ep})不一致"
            )
        body = {
            "book_id": str(book_id),
            "book_name": book_name,
            "item_ids": [str(i) for i in item_ids],
            "chapter_start": from_ep,
            "chapter_end": to_ep,
            "content_genre": 2,
            "aweme_user_new_version": True,
        }
        return self._api_post(BATCH_DOWNLOAD_PATH, body)

    def batch_download_in_range(
        self, book_id: str, book_name: str, from_ep: int, to_ep: int
    ) -> dict[str, Any]:
        ep_json = self.fetch_episodes_in_range(book_id, from_ep, to_ep)
        episodes = (ep_json.get("data") or {}).get("data") or []
        if not episodes:
            raise RuntimeError("未获取到集数信息")
        sliced = episodes[from_ep - 1 : to_ep]
        need = to_ep - from_ep + 1
        if len(sliced) != need:
            raise RuntimeError(
                f"集数不足：需要第 {from_ep}-{to_ep} 集（共 {need} 集），"
                f"实际仅拿到 {len(sliced)} 集（列表共 {len(episodes)} 集）"
            )
        item_ids = [ep["item_id"] for ep in sliced]
        return self.create_batch_download_task(
            book_id=book_id,
            book_name=book_name,
            item_ids=item_ids,
            from_ep=from_ep,
            to_ep=to_ep,
        )

    def _resolve_task_list_time_range(self, opts: dict[str, Any]) -> dict[str, str]:
        if "start_time" in opts and "end_time" in opts:
            return {
                "start_time": str(opts.pop("start_time")),
                "end_time": str(opts.pop("end_time")),
            }
        days = int(opts.pop("days", 30))
        return self._default_unix_time_range(days)

    def fetch_download_task_list(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        opts = dict(options or {})
        time_range = self._resolve_task_list_time_range(opts)
        params = {**time_range, "page_index": "0", "page_size": "10", **opts}
        referer = (
            "https://www.changdupingtai.com/sale/download-center"
            f"?start_time={params['start_time']}&end_time={params['end_time']}"
            f"&page_index=1&page_size={params['page_size']}"
        )
        return self._api_fetch(DOWNLOAD_TASK_LIST_PATH, params, platform=True, referer=referer)

    def find_download_task(self, download_id: str, options: dict[str, Any] | None = None) -> dict[str, Any] | None:
        opts = dict(options or {})
        page_size = int(opts.pop("page_size", 10))
        max_pages = int(opts.pop("maxPages", 50))
        time_range = self._resolve_task_list_time_range(opts)

        for page in range(max_pages):
            json_data = self.fetch_download_task_list(
                {**time_range, "page_index": str(page), "page_size": str(page_size), **opts}
            )
            hit = next(
                (t for t in (json_data.get("data") or []) if str(t.get("download_id")) == str(download_id)),
                None,
            )
            if hit:
                return hit
            total = json_data.get("total") or 0
            if (page + 1) * page_size >= total:
                break
        return None

    def fetch_download_tasks_by_ids(
        self,
        download_ids,
        *,
        start_time: str | None = None,
        end_time: str | None = None,
        page_size: int = 50,
        max_bulk_pages: int = 3,
        **opts: Any,
    ) -> dict[str, dict[str, Any]]:
        """批量查询转码任务：先拉列表前若干页，未命中再逐个兜底查询。"""
        ids = {str(i) for i in download_ids if i}
        if not ids:
            return {}

        query_opts: dict[str, Any] = dict(opts)
        if start_time is not None and end_time is not None:
            query_opts["start_time"] = start_time
            query_opts["end_time"] = end_time

        found: dict[str, dict[str, Any]] = {}
        list_opts = {**query_opts, "page_size": page_size}

        for page in range(max_bulk_pages):
            json_data = self.fetch_download_task_list(
                {**list_opts, "page_index": str(page)}
            )
            for task in json_data.get("data") or []:
                download_id = str(task.get("download_id") or "")
                if download_id in ids and download_id not in found:
                    found[download_id] = task
            if len(found) >= len(ids):
                break
            total = int(json_data.get("total") or 0)
            if (page + 1) * page_size >= total:
                break

        missing = ids - found.keys()
        if missing:
            fallback_opts = {**query_opts, "page_size": page_size}
            for download_id in missing:
                hit = self.find_download_task(download_id, fallback_opts)
                if hit:
                    found[download_id] = hit
        return found

    def fetch_download_url(self, imagex_uri: str) -> str:
        json_data = self._api_fetch(
            DOWNLOAD_GET_URL_PATH,
            {"imagex_uri": imagex_uri},
            platform=True,
            referer="https://www.changdupingtai.com/sale/download-center",
        )
        if json_data.get("code") != 0 or not json_data.get("download_url"):
            raise RuntimeError(f"获取下载链接失败: {json.dumps(json_data, ensure_ascii=False)}")
        return json_data["download_url"]

    @staticmethod
    def _sanitize_file_name(name: str) -> str:
        return re.sub(r"\s+", "", re.sub(r'[\\/:*?"<>|]', "_", name))

    def _resolve_download_path(self, book_name: str, download_dir: Path | str | None = None) -> Path:
        download_dir = Path(download_dir or DEFAULT_DOWNLOAD_DIR)
        download_dir.mkdir(parents=True, exist_ok=True)
        base = self._sanitize_file_name(book_name)
        file_path = download_dir / f"{base}.zip"
        counter = 1
        while file_path.exists():
            file_path = download_dir / f"{base}_{counter}.zip"
            counter += 1
        return file_path

    def download_zip_from_url(
        self,
        url: str,
        dest_path: Path | str,
        *,
        timeout_ms: int = 10 * 60 * 1000,
        min_speed_kbps: int = 300,
        warmup_sec: int = 20,
        stall_sec: int = 45,
        slow_window_sec: int = 30,
        cancel_check: Callable[[], bool] | None = None,
        progress_callback: Callable[[int, int | None, float], None] | None = None,
    ) -> dict[str, Any]:
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        abort_reason: str | None = None
        last_speed_kbps = 0.0
        downloaded = 0
        last_byte_at = time.time()
        start_at = time.time()
        chunks: list[tuple[float, int]] = []
        done_event = threading.Event()
        total_bytes: int | None = None
        last_progress_at = 0.0
        last_progress_downloaded = 0

        def emit_progress(force: bool = False) -> None:
            nonlocal last_progress_at, last_progress_downloaded
            if not progress_callback:
                return
            now = time.time()
            if not force and now - last_progress_at < 1.0:
                return
            elapsed = now - last_progress_at if last_progress_at else 0.0
            delta = downloaded - last_progress_downloaded
            if elapsed > 0 and delta > 0:
                speed_kbps = delta / 1024 / elapsed
            else:
                speed_kbps = last_speed_kbps
            last_progress_at = now
            last_progress_downloaded = downloaded
            progress_callback(downloaded, total_bytes, speed_kbps)

        def prune_chunks(cutoff: float) -> None:
            while chunks and chunks[0][0] < cutoff:
                chunks.pop(0)

        def monitor() -> None:
            nonlocal abort_reason, last_speed_kbps
            while not done_event.wait(5):
                if abort_reason:
                    return
                if cancel_check and cancel_check():
                    abort_reason = "cancelled"
                    return
                now = time.time()
                if (now - start_at) * 1000 >= timeout_ms:
                    abort_reason = "total_timeout"
                    return
                if now - start_at < warmup_sec:
                    continue
                if now - last_byte_at >= stall_sec:
                    abort_reason = "stall"
                    return
                prune_chunks(now - slow_window_sec)
                window_bytes = sum(length for _, length in chunks)
                last_speed_kbps = window_bytes / 1024 / slow_window_sec
                if downloaded > 0 and last_speed_kbps < min_speed_kbps:
                    abort_reason = "slow"

        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()

        try:
            response = requests.get(
                url,
                stream=True,
                timeout=(30, 120),
                headers=zip_download_headers(cookie=self._cookie_header or None),
            )
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length and str(content_length).isdigit():
                total_bytes = int(content_length)
            emit_progress(force=True)
            with open(dest_path, "wb") as writer:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if abort_reason:
                        break
                    if cancel_check and cancel_check():
                        abort_reason = "cancelled"
                        break
                    if not chunk:
                        continue
                    now = time.time()
                    downloaded += len(chunk)
                    last_byte_at = now
                    chunks.append((now, len(chunk)))
                    writer.write(chunk)
                    emit_progress()
            emit_progress(force=True)
        finally:
            done_event.set()
            monitor_thread.join(timeout=1)

        if abort_reason:
            if dest_path.exists():
                dest_path.unlink(missing_ok=True)
            if abort_reason == "stall":
                raise RuntimeError(f"下载停滞（{stall_sec} 秒无数据，已取消）")
            if abort_reason == "slow":
                raise RuntimeError(
                    f"下载速度过慢（最近 {slow_window_sec}s 平均 {int(last_speed_kbps)} KB/s，"
                    f"阈值 {min_speed_kbps} KB/s）"
                )
            if abort_reason == "total_timeout":
                raise RuntimeError(f"下载超时（{timeout_ms // 60000} 分钟未完成）")
            if abort_reason == "cancelled":
                raise RuntimeError("下载已取消")

        elapsed_sec = time.time() - start_at
        avg_speed = downloaded / 1024 / elapsed_sec if elapsed_sec > 0 else 0
        return {
            "filePath": str(dest_path),
            "downloaded": downloaded,
            "avgSpeedKbps": round(avg_speed),
            "elapsedSec": round(elapsed_sec),
        }

    def prepare_task_zip_download(
        self,
        download_id: str,
        *,
        download_dir: Path | str | None = None,
        dest_path: Path | str | None = None,
    ) -> dict[str, Any]:
        """在 Playwright 线程查询任务并获取下载 URL（不含实际文件下载）。"""
        self._assert_playwright_thread()
        task = self.find_download_task(download_id)
        if not task:
            raise RuntimeError(f"未找到下载任务: {download_id}")
        if task.get("task_status") != DOWNLOAD_TASK_STATUS_DONE:
            raise RuntimeError(
                f"任务未完成，当前 status={task.get('task_status')}: {download_id}"
            )
        if not task.get("imagex_uri"):
            raise RuntimeError(f"任务缺少 imagex_uri: {download_id}")

        download_url = self.fetch_download_url(task["imagex_uri"])
        resolved = Path(dest_path) if dest_path else self._resolve_download_path(
            task.get("book_name") or download_id, download_dir
        )
        self._refresh_cookie_header()
        return {
            "downloadId": download_id,
            "bookName": task.get("book_name"),
            "taskName": task.get("task_name"),
            "downloadUrl": download_url,
            "destPath": resolved,
        }

    def _refresh_cookie_header(self) -> None:
        """在 Playwright 线程刷新 Cookie，供 zip 下载请求头使用。"""
        if self.context is None:
            return
        try:
            self._cookie_header = format_cookie_header(self.context.cookies())
        except Exception:
            pass

    def download_task_zip(
        self,
        download_id: str,
        *,
        wait_for_done: bool = True,
        download_dir: Path | str | None = None,
        dest_path: Path | str | None = None,
        download_timeout_ms: int = 10 * 60 * 1000,
        min_speed_kbps: int = 300,
        warmup_sec: int = 20,
        stall_sec: int = 45,
        slow_window_sec: int = 30,
        interval_ms: int = 5000,
        timeout_ms: int = 10 * 60 * 1000,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict[str, Any]:
        self._assert_playwright_thread()
        task = self.find_download_task(download_id)
        if wait_for_done:
            deadline = time.time() + timeout_ms / 1000
            while not task or task.get("task_status") != DOWNLOAD_TASK_STATUS_DONE:
                if cancel_check and cancel_check():
                    raise RuntimeError("下载已取消")
                if time.time() > deadline:
                    raise RuntimeError(f"等待下载任务超时: {download_id}")
                assert self.page
                self.page.wait_for_timeout(interval_ms)
                task = self.find_download_task(download_id)

        prepared = self.prepare_task_zip_download(
            download_id,
            download_dir=download_dir,
            dest_path=dest_path,
        )
        dl_stats = self.download_zip_from_url(
            prepared["downloadUrl"],
            prepared["destPath"],
            timeout_ms=download_timeout_ms,
            min_speed_kbps=min_speed_kbps,
            warmup_sec=warmup_sec,
            stall_sec=stall_sec,
            slow_window_sec=slow_window_sec,
            cancel_check=cancel_check,
        )
        return {
            "downloadId": download_id,
            "bookName": prepared["bookName"],
            "taskName": prepared["taskName"],
            "filePath": dl_stats["filePath"],
            "downloadUrl": prepared["downloadUrl"],
            "avgSpeedKbps": dl_stats["avgSpeedKbps"],
            "elapsedSec": dl_stats["elapsedSec"],
        }

    def check_auth(self) -> dict[str, Any]:
        json_data = self.fetch_list({"page_index": "0", "page_size": "1"})
        return {
            "ok": json_data.get("code") == 0,
            "code": json_data.get("code"),
            "message": json_data.get("message"),
            "total": (json_data.get("data") or {}).get("total"),
        }

    def search_by_name(self, keyword: str, options: dict[str, Any] | None = None) -> dict[str, Any]:
        """按剧名搜索。参数对齐常读短剧列表页（含日期范围，不含 content_genre）。"""
        date_range = self._default_series_date_range()
        params = {
            "search_type": "2",
            "query": keyword,
            "sort_type": "1",
            **date_range,
            "sort_field": "8",
            "aweme_user_new_version": "true",
            "page_index": "0",
            "page_size": "10",
            **(options or {}),
        }
        # 与网站一致：先拉一页列表再按剧名搜（否则部分剧名会返回 total=0）
        self._api_fetch(
            SERIES_LIST_PATH,
            {
                "sort_type": "1",
                **date_range,
                "sort_field": "8",
                "aweme_user_new_version": "true",
                "page_index": "0",
                "page_size": "10",
            },
            referer=SHORT_PLAY_LIST_REFERER,
            content_api=True,
        )
        return self._api_fetch(
            SERIES_LIST_PATH, params, referer=SHORT_PLAY_LIST_REFERER, content_api=True
        )

    def _search_by_name_via_ui_trigger(self, keyword: str) -> dict[str, Any]:
        """通过页面筛选框触发搜索，拦截网站原生请求（与手动搜索一致）。"""
        from urllib.parse import parse_qs, unquote, urlparse

        self._assert_playwright_thread()
        assert self.page
        captured: dict[str, Any] = {}

        def on_response(response):
            if SERIES_LIST_PATH not in response.url:
                return
            qs = parse_qs(urlparse(response.url).query)
            q = unquote((qs.get("query") or [""])[0])
            if q != keyword:
                return
            try:
                body = response.json()
            except Exception:
                return
            inner = body.get("data") or {}
            if inner.get("data") or int(inner.get("total") or 0) > 0:
                captured["body"] = body

        self.page.on("response", on_response)
        try:
            self._goto_short_play_list()
            self.page.wait_for_timeout(2000)
            triggered = self.page.evaluate(
                """(keyword) => {
                    const inputs = [...document.querySelectorAll('input')];
                    for (const el of inputs) {
                        const style = window.getComputedStyle(el);
                        if (style.display === 'none' || style.visibility === 'hidden') continue;
                        const meta = (el.placeholder || '') + (el.getAttribute('aria-label') || '');
                        if (/剧|搜|名称|短剧/.test(meta) || el.closest('[class*=search]')) {
                            el.focus();
                            el.value = keyword;
                            el.dispatchEvent(new InputEvent('input', { bubbles: true, data: keyword }));
                            el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
                            return true;
                        }
                    }
                    return false;
                }""",
                keyword,
            )
            if not triggered:
                self.page.keyboard.type(keyword, delay=30)
                self.page.keyboard.press("Enter")
            self.page.wait_for_timeout(5000)
        finally:
            self.page.remove_listener("response", on_response)

        body = captured.get("body")
        if body:
            return body
        raise RuntimeError(f"页面搜索未返回结果: {keyword}")

    def find_drama_by_name(self, name: str) -> dict[str, Any]:
        """按剧名搜索并返回最佳匹配；失败时抛出带原因的 RuntimeError。"""
        keywords = drama_search_keywords(name)
        if not keywords:
            raise RuntimeError("剧名不能为空")

        seen_ids: set[str] = set()
        candidates: list[dict[str, Any]] = []
        restricted = False

        for keyword in keywords:
            search = self.search_by_name(keyword)
            inner = search.get("data") or {}
            rows = inner.get("data") or []
            total = int(inner.get("total") or 0)
            if not rows:
                try:
                    search = self._search_by_name_via_ui_trigger(keyword)
                    inner = search.get("data") or {}
                    rows = inner.get("data") or []
                    total = int(inner.get("total") or 0)
                except RuntimeError:
                    pass
            if total > 0 and not rows:
                restricted = True
            for row in rows:
                book_id = str(row.get("book_id") or "")
                if book_id and book_id not in seen_ids:
                    seen_ids.add(book_id)
                    candidates.append(row)

        if not candidates:
            try:
                search = self._search_by_name_via_ui_trigger(name)
                inner = search.get("data") or {}
                rows = inner.get("data") or []
                for row in rows:
                    book_id = str(row.get("book_id") or "")
                    if book_id and book_id not in seen_ids:
                        seen_ids.add(book_id)
                        candidates.append(row)
            except RuntimeError:
                pass
        if not candidates:
            if restricted:
                raise RuntimeError(
                    f"剧「{name}」在常读平台有记录，但当前账号无法获取详情。"
                    "请在常读短剧列表确认是否有下载权限，或重新登录后再试。"
                )
            raise RuntimeError(
                f"未搜到剧「{name}」。请核对剧名是否与常读平台完全一致（含标点）。"
            )

        drama = pick_drama_match(candidates, name)
        if drama is None:
            raise RuntimeError(f"未搜到剧「{name}」")
        return drama


def drama_search_keywords(name: str) -> list[str]:
    name = name.strip()
    if not name:
        return []
    keywords = [name]
    for sep in ("，", ",", ":", "：", "|", "/"):
        if sep not in name:
            continue
        for part in name.split(sep):
            part = part.strip()
            if part and part not in keywords:
                keywords.append(part)
    return keywords


def normalize_drama_name(name: str) -> str:
    return re.sub(r"\s+", "", name)


def pick_drama_match(
    candidates: list[dict[str, Any]], query: str
) -> dict[str, Any] | None:
    if not candidates:
        return None
    query_norm = normalize_drama_name(query)
    for row in candidates:
        series_name = row.get("series_name") or ""
        if normalize_drama_name(series_name) == query_norm:
            return row
    for row in candidates:
        series_name = normalize_drama_name(row.get("series_name") or "")
        if query_norm in series_name or series_name in query_norm:
            return row
    return candidates[0]
