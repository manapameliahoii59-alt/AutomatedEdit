import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QTimer, Signal
from qfluentwidgets import qconfig

from app.common.aes import aes_encrypt
from app.common.config import cfg
from app.core.playwright_worker import playwright_worker
from app.core.task_manager import task_manager
from app.core.view_model import ViewModel
from app.data.api.api import get_api
from app.data.services.batch_download_service import (
    BatchDownloadOptions,
    clear_download_done_records,
    format_download_progress,
    run_batch_download,
)
from app.data.services.changdu_login_service import (
    clear_auth_file,
    get_changdu_credentials,
    is_auth_file_present,
    run_changdu_login,
)
from app.data.services.changdu_paths import resolve_video_download_root
from app.data.services.series_list_client import SeriesListClient
from app.data.services.usage_service import UsageService
from app.data.services.quota_service import QuotaService

MAX_DOWNLOAD_EPISODE = 15


def _format_changdu_precheck_error(detail: str) -> str:
    """将常读前置检查失败映射为可读错误（避免把业务错误当成登录过期）。"""
    text = (detail or "").strip() or "未知错误"
    if any(k in text for k in ("查询时间", "查询天数", "最大查询")):
        return f"剧目列表查询参数无效：{text}"
    if any(k in text for k in ("登录", "未登录", "过期", "passport", "401", "403")):
        return f"登录态已过期，请重新登录常读平台（{text}）"
    return f"剧目查询前置检查失败：{text}"


def _is_changdu_auth_expired_error(msg: str) -> bool:
    """识别常读登录态失效（含 cookie 缺失、过期提示等）。"""
    text = (msg or "").strip()
    if not text:
        return False
    return any(
        k in text
        for k in (
            "登录态已过期",
            "登录可能已过期",
            "缺少 adUserId",
            "缺少 rootAdUserId",
            "请重新登录",
            "请先登录常读",
            "未登录常读",
        )
    )


@dataclass
class VideoDownloadTarget:
    id: str
    name: str
    from_ep: int
    to_ep: int
    status: str = "待下载"
    extra: dict = field(default_factory=dict)


class VideoDownloadViewModel(ViewModel):
    targetsChanged = Signal(list)
    loadingChanged = Signal(bool, str, str)  # loading, title, content
    logAppended = Signal(str)
    targetProgressChanged = Signal(str, str)
    authStatusChanged = Signal(bool, str)
    messageReceived = Signal(str)
    errorOccurred = Signal(str)
    handoffToClipEdit = Signal(list)  # folders: list[str]
    clipHandoffRequested = Signal(list, bool, bool, bool)  # folders, run_plan, run_render, switch_tab (kept for compat)
    transcribeDoneForClip = Signal(str)
    settingsLoaded = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._targets: list[VideoDownloadTarget] = []
        self._active_tasks = 0
        self._cancel_requested = False
        self._default_from = 1
        self._default_to = MAX_DOWNLOAD_EPISODE
        self.targetsChanged.emit(self._targets)
        self._load_settings_from_server()

    def refresh_auth_status(self) -> None:
        self._refresh_auth_status()

    def get_targets(self) -> list[VideoDownloadTarget]:
        return list(self._targets)

    def get_default_from(self) -> int:
        return self._default_from

    def get_default_to(self) -> int:
        return self._default_to

    def set_default_range(self, from_ep: int, to_ep: int) -> None:
        self._default_from = max(1, min(from_ep, MAX_DOWNLOAD_EPISODE))
        self._default_to = max(
            self._default_from, min(to_ep, MAX_DOWNLOAD_EPISODE)
        )

    def _apply_video_download_settings(self, vd: dict) -> None:
        if vd.get("episode_from") is not None:
            self._default_from = max(1, min(int(vd["episode_from"]), MAX_DOWNLOAD_EPISODE))
        if vd.get("episode_to") is not None:
            self._default_to = max(self._default_from, min(int(vd["episode_to"]), MAX_DOWNLOAD_EPISODE))
        if vd.get("download_dir"):
            qconfig.set(cfg.video_download_dir, vd["download_dir"])
        if vd.get("auto_unzip") is not None:
            qconfig.set(cfg.video_download_auto_unzip, bool(vd["auto_unzip"]))
        if vd.get("auto_batch_all") is not None:
            qconfig.set(cfg.video_download_auto_batch_all, bool(vd["auto_batch_all"]))
        elif vd.get("auto_import_clip") is not None:
            qconfig.set(cfg.video_download_auto_batch_all, bool(vd["auto_import_clip"]))
        if vd.get("auto_transcribe") is not None:
            qconfig.set(cfg.video_download_auto_transcribe, bool(vd["auto_transcribe"]))
        if vd.get("auto_plan") is not None:
            qconfig.set(cfg.video_download_auto_plan, bool(vd["auto_plan"]))
        if vd.get("auto_import_clip") is not None:
            qconfig.set(cfg.video_download_auto_import_clip, bool(vd["auto_import_clip"]))
        if vd.get("auto_start_after_add") is not None:
            qconfig.set(cfg.video_download_auto_start_after_add, bool(vd["auto_start_after_add"]))
        if vd.get("changdu_email"):
            qconfig.set(cfg.changdu_email, vd["changdu_email"])
        if vd.get("changdu_password"):
            qconfig.set(cfg.changdu_password, aes_encrypt(vd["changdu_password"]))

    def _load_settings_from_server(self) -> None:
        """后台拉取服务端设置，避免初始化时卡住界面。"""

        def _do():
            api = get_api()
            if not api._token:
                return None
            return api.get_settings()

        def _on_success(data):
            if not data:
                return
            vd = data.get("video_download") or {}
            self._apply_video_download_settings(vd)
            from app.common.plan_settings import apply_plan_settings_dict

            apply_plan_settings_dict(data.get("plan"))
            from app.common.overlay_text_settings import apply_overlay_from_clip_edit_dict

            clip_edit = data.get("clip_edit") or {}
            apply_overlay_from_clip_edit_dict(clip_edit)
            self.settingsLoaded.emit(vd)

        def _on_error(_msg: str):
            # 进页同步失败不打扰用户，沿用本地 config
            pass

        task_manager.submit_task(_do, on_success=_on_success, on_error=_on_error)

    def save_to_server(
        self,
        patch: dict,
        *,
        show_loading: bool = True,
        notify_success: bool = True,
    ) -> None:
        """本地已改完后，后台同步到服务端。"""
        api = get_api()
        if not api._token:
            return

        if show_loading:
            self._add_task("正在保存设置", "正在同步到服务器，请稍候…")

        def _do():
            get_api().update_settings(patch)
            return True

        def _on_success(_ok):
            if show_loading:
                self._remove_task()
            if notify_success:
                self.messageReceived.emit("设置已保存")

        def _on_error(msg: str):
            if show_loading:
                self._remove_task()
            self.errorOccurred.emit(f"设置保存失败：{msg}")

        task_manager.submit_task(_do, on_success=_on_success, on_error=_on_error)

    def _refresh_auth_status(self) -> None:
        if is_auth_file_present():
            self.authStatusChanged.emit(True, "已登录")
        else:
            self.authStatusChanged.emit(False, "未登录常读平台")

    def _append_log(self, line: str) -> None:
        self.logAppended.emit(line)

    def _add_task(self, title: str = "正在处理", content: str = "请稍候…") -> None:
        self._active_tasks += 1
        self._cancel_requested = False
        if self._active_tasks == 1:
            self.loadingChanged.emit(True, title, content)

    def _remove_task(self) -> None:
        if self._active_tasks > 0:
            self._active_tasks -= 1
        if self._active_tasks <= 0:
            self._active_tasks = 0
            self.loadingChanged.emit(False, "", "")

    def request_cancel(self) -> None:
        self._cancel_requested = True
        self._append_log("正在取消…")

    def _is_cancelled(self) -> bool:
        return self._cancel_requested

    def _finish_task_with_error(self, msg: str, *, cancelled_message: str) -> bool:
        """结束任务；若为取消则提示并返回 True。"""
        self._remove_task()
        if "已取消" in msg:
            self._append_log("任务已取消")
            self.messageReceived.emit(cancelled_message)
            return True
        return False

    def _relogin_changdu_after_expired(self, detail: str = "") -> None:
        """清除失效登录态并打开浏览器，引导用户重新登录。"""
        clear_auth_file()
        self.authStatusChanged.emit(False, "登录已过期")
        if detail:
            self._append_log(f"⚠️ 登录态失效：{detail}")
        self.messageReceived.emit(
            "登录态已过期，已自动清除。正在打开浏览器，请重新登录常读平台"
        )
        # 延后一拍，确保当前任务已卸完 busy 态后再开登录
        QTimer.singleShot(0, self.login_changdu)

    def login_changdu(self) -> None:
        if self._active_tasks > 0:
            self.messageReceived.emit("当前有任务进行中，请完成后再登录")
            return

        if get_changdu_credentials():
            hint = "已自动填入账号密码，请勾选协议、完成拖动验证并点击登录"
        else:
            hint = "请在浏览器中完成常读平台登录"
        self._add_task("正在打开浏览器", hint)

        def _do_login():
            return str(playwright_worker.run(run_changdu_login))

        def _on_success(path: str):
            self._remove_task()
            self.refresh_auth_status()
            self.messageReceived.emit("登录成功")

        def _on_error(msg: str):
            self._remove_task()
            self.errorOccurred.emit(f"登录失败：{msg}")

        task_manager.submit_task(_do_login, on_success=_on_success, on_error=_on_error)

    def check_auth(self) -> None:
        if not is_auth_file_present():
            self._relogin_changdu_after_expired("未找到登录态")
            return
        if self._active_tasks > 0:
            self.messageReceived.emit("当前有任务进行中，请稍候")
            return

        self._add_task("正在验证登录态", "正在检查常读平台登录是否有效…")

        def _do_check():
            def _check():
                with SeriesListClient(headless=True) as client:
                    return client.check_auth()

            return playwright_worker.run(_check)

        def _on_success(result: dict):
            self._remove_task()
            if result.get("ok"):
                self.authStatusChanged.emit(True, "登录态有效")
                self.messageReceived.emit("常读平台登录态有效")
                return
            detail = str(result.get("message") or result.get("code") or "未知错误")
            msg = _format_changdu_precheck_error(detail)
            if _is_changdu_auth_expired_error(msg):
                self._relogin_changdu_after_expired(msg)
                return
            self.errorOccurred.emit(msg)

        def _on_error(msg: str):
            self._remove_task()
            if _is_changdu_auth_expired_error(msg):
                self._relogin_changdu_after_expired(msg)
                return
            self.errorOccurred.emit(f"验证失败：{msg}")

        task_manager.submit_task(_do_check, on_success=_on_success, on_error=_on_error)

    def clear_auth(self) -> None:
        if self._active_tasks > 0:
            self.messageReceived.emit("当前有任务进行中，请稍候")
            return
        if not clear_auth_file():
            self.messageReceived.emit("当前没有可删除的登录态")
            return
        self.refresh_auth_status()
        self.messageReceived.emit("登录态已删除")

    def reset_download_records(self) -> None:
        """清空已下载记录，允许再次下载相同剧目。"""
        if self._active_tasks > 0:
            self.messageReceived.emit("当前有任务进行中，请稍候")
            return
        count = clear_download_done_records()
        if count <= 0:
            self.messageReceived.emit("当前没有可重置的下载记录")
            return
        self.messageReceived.emit(f"已重置下载记录（{count} 条），可重新下载相同剧目")

    def add_targets_from_text_with_lookup(self, text: str, *, auto_start: bool = False) -> None:
        names = [line.strip() for line in text.splitlines() if line.strip()]
        if not names:
            self.errorOccurred.emit("请至少输入一个剧名（每行一个）")
            return
        if not is_auth_file_present():
            self._relogin_changdu_after_expired("未找到登录态")
            return
        if self._active_tasks > 0:
            self.messageReceived.emit("当前有任务进行中，请稍候")
            return

        self._add_task("正在添加剧目", "先验证登录态，再查询剧名…")

        def _do_lookup():
            def _run():
                with SeriesListClient(headless=True) as client:
                    auth = client.check_auth()
                    if not auth.get("ok"):
                        detail = str(
                            auth.get("message") or auth.get("code") or "未知错误"
                        )
                        raise RuntimeError(_format_changdu_precheck_error(detail))
                    if self._is_cancelled():
                        raise RuntimeError("任务已取消")

                    results = []
                    for i, name in enumerate(names):
                        if self._is_cancelled():
                            raise RuntimeError("任务已取消")
                        if i > 0:
                            import random
                            import time
                            time.sleep(random.uniform(0.6, 1.3))
                        try:
                            drama = client.find_drama_by_name(name)
                            results.append(
                                {
                                    "input_name": name,
                                    "ok": True,
                                    "matched_name": drama.get("series_name") or name,
                                    "drama_meta": drama,
                                }
                            )
                        except RuntimeError as exc:
                            if self._is_cancelled() or "已取消" in str(exc):
                                raise RuntimeError("任务已取消") from exc
                            results.append(
                                {"input_name": name, "ok": False, "error": str(exc)}
                            )
                    if self._is_cancelled():
                        raise RuntimeError("任务已取消")
                    return results

            return playwright_worker.run(_run)

        def _on_success(results: list[dict]):
            self._remove_task()
            self.authStatusChanged.emit(True, "登录态有效")
            ok = [r for r in results if r["ok"]]
            failed = [r for r in results if not r["ok"]]

            if failed and not ok:
                lines = "\n".join(f"· {r['input_name']}：{r['error']}" for r in failed)
                self.errorOccurred.emit(f"以下剧目无法添加：\n{lines}")
                return

            for row in ok:
                meta = row.get("drama_meta") or {}
                self._targets.append(
                    VideoDownloadTarget(
                        id=uuid.uuid4().hex,
                        name=row["matched_name"],
                        from_ep=self._default_from,
                        to_ep=self._default_to,
                        extra={
                            "book_id": meta.get("book_id"),
                            "episode_amount": meta.get("episode_amount"),
                            "author": meta.get("author"),
                        },
                    )
                )
            self.targetsChanged.emit(self._targets)

            if failed:
                lines = "\n".join(f"· {r['input_name']}：{r['error']}" for r in failed)
                self.messageReceived.emit(
                    f"已添加 {len(ok)} 个剧目。以下未能匹配：\n{lines}"
                )
            else:
                self.messageReceived.emit(f"已添加 {len(ok)} 个剧目")

            if auto_start and ok:
                self.start_download()

        def _on_error(msg: str):
            if self._finish_task_with_error(msg, cancelled_message="剧名验证已取消"):
                return
            if _is_changdu_auth_expired_error(msg):
                self._relogin_changdu_after_expired(msg)
                return
            self.errorOccurred.emit(f"剧名验证失败：{msg}")

        task_manager.submit_task(_do_lookup, on_success=_on_success, on_error=_on_error)

    def remove_target(self, target_id: str) -> None:
        self._targets = [t for t in self._targets if t.id != target_id]
        self.targetsChanged.emit(self._targets)

    def _targets_to_payload(self) -> list[dict]:
        payload = []
        for t in self._targets:
            if t.extra.get("mode") == "id" or t.extra.get("task_id"):
                payload.append({"id": t.extra.get("task_id") or t.name})
            else:
                item_payload = {
                    "name": t.name,
                    "from": t.from_ep,
                    "to": t.to_ep,
                }
                if t.extra.get("book_id"):
                    item_payload["bookId"] = t.extra["book_id"]
                if t.extra.get("episode_amount"):
                    item_payload["episodeAmount"] = t.extra["episode_amount"]
                payload.append(item_payload)
        return payload

    def _update_target_status(self, label: str, status: str) -> None:
        for target in self._targets:
            if target.name == label:
                target.status = status
                self.targetProgressChanged.emit(label, status)
                return

    def _handle_download_progress(
        self,
        label: str,
        downloaded: int,
        total: int | None,
        speed_kbps: float,
    ) -> None:
        status = format_download_progress(downloaded, total, speed_kbps)
        self._update_target_status(label, status)

    def _set_all_status(self, status: str) -> None:
        for t in self._targets:
            t.status = status
        self.targetsChanged.emit(self._targets)

    def _ensure_can_download(self) -> bool:
        names = [t.name for t in self._targets if (t.name or "").strip()]
        qs = QuotaService.instance()
        if not names:
            quota = qs.refresh()
            if not quota.download_enabled:
                self.errorOccurred.emit("当前无法使用视频下载")
                return False
            return True
        allowed, message = qs.can_download(names)
        if not allowed:
            self.errorOccurred.emit(message or "当前无法使用视频下载")
            return False
        probe = next(
            (n for n in names if n not in qs.get_quota().downloaded_dramas),
            names[0],
        )
        ok, remote_msg = qs.check_remote("download", probe)
        if not ok:
            self.errorOccurred.emit(remote_msg or "当前无法使用视频下载")
            return False
        return True

    def start_download(self, *, create_only: bool = False, download_only: bool = False) -> None:
        if not is_auth_file_present():
            self._relogin_changdu_after_expired("未找到登录态")
            return
        if not download_only and not self._targets:
            self.errorOccurred.emit("请先添加下载剧目")
            return
        if self._active_tasks > 0:
            self.messageReceived.emit("当前有任务进行中，请稍候")
            return
        if not self._ensure_can_download():
            return

        self._add_task("正在下载", "视频下载任务进行中，请稍候…")
        self._set_all_status("处理中" if not create_only else "创建任务中")
        targets_payload = self._targets_to_payload()

        opts = BatchDownloadOptions(
            download_dir=resolve_video_download_root(),
            create_only=create_only,
            download_only=download_only,
            from_ep=self._default_from,
            to_ep=self._default_to,
            cancel_check=lambda: self._cancel_requested,
            auto_unzip_and_delete=cfg.video_download_auto_unzip.value,
            auto_transcribe=False,
            on_transcribe_done=None,
            on_download_progress=self._handle_download_progress,
            on_target_status=self._update_target_status,
        )

        def _do_download():
            def ui_log(line: str):
                self._append_log(line)

            def _run():
                return run_batch_download(targets_payload, opts, log=ui_log, dev_log=print)

            return playwright_worker.run(_run)

        def _on_success(_result: dict):
            # 先清忙态，避免后续 handoff/上报异常导致「正在下载」一直挂着
            self._remove_task()
            try:
                if create_only:
                    for t in self._targets:
                        t.status = "已创建"
                else:
                    for t in self._targets:
                        if t.status in ("处理中", "转码中") or t.status.startswith("下载中"):
                            t.status = "已完成"
                self.targetsChanged.emit(self._targets)
                if create_only:
                    self.messageReceived.emit("下载任务已创建，可稍后点击「继续下载」")
                    return
                self.messageReceived.emit("批量下载流程已结束，详见下方日志")
                downloaded = [t.name for t in self._targets if t.status == "已完成"]
                UsageService.report_download_dramas(downloaded)

                folders = (_result or {}).get("downloaded_folders") or []
                if not folders and not create_only:
                    root = Path(resolve_video_download_root())
                    for t in self._targets:
                        if t.status == "已完成":
                            cand = root / t.name
                            if cand.is_dir():
                                folders.append(str(cand))

                if cfg.video_download_auto_batch_all.value and folders:
                    self._append_log(
                        f"   🚀 下载完成，正在导入自动化剪辑并开启一键执行（共 {len(folders)} 部）…"
                    )
                    self.handoffToClipEdit.emit(folders)
            except Exception as exc:
                self._append_log(f"❌ 下载收尾异常: {exc}")
                self.errorOccurred.emit(f"下载已完成，但收尾处理失败：{exc}")

        def _on_error(msg: str):
            cancelled = "已取消" in msg
            active_statuses = ("处理中", "创建任务中", "转码中")
            for t in self._targets:
                active = t.status in active_statuses or t.status.startswith("下载中")
                if active:
                    t.status = "已取消" if cancelled else "失败"
            self.targetsChanged.emit(self._targets)
            if self._finish_task_with_error(msg, cancelled_message="下载已取消"):
                return
            self._append_log(f"❌ {msg}")
            self.errorOccurred.emit(msg)

        task_manager.submit_task(_do_download, on_success=_on_success, on_error=_on_error)

    def set_download_dir(self, path: str) -> None:
        cfg.video_download_dir.value = path.strip()
        qconfig.save()
