"""常读平台两阶段批量下载（创建任务 → 轮询转码 → 并行下载 zip）。"""

from __future__ import annotations

import json
import time
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.common.runtime import is_dev_runtime
from app.data.services.changdu_paths import (
    DEFAULT_DOWNLOAD_DIR,
    DONE_FILE,
    LOG_FILE,
    PENDING_FILE,
    ensure_changdu_dirs,
)
from app.data.services.drama_folder_service import DramaFolderError, scan_drama_folder
from app.data.services.series_list_client import (
    DOWNLOAD_TASK_STATUS_DONE,
    SeriesListClient,
)
from app.data.services.transcription_service import TranscriptionService
from app.data.models.drama_project import DramaProject

DEFAULT_FROM_EP = 1
DEFAULT_TO_EP = 10
DEFAULT_CONCURRENT_DOWNLOADS = 3
DEFAULT_DOWNLOAD_TIMEOUT_MIN = 10
DEFAULT_DOWNLOAD_RETRIES = 2
DEFAULT_MIN_SPEED_KBPS = 300
DEFAULT_WARMUP_SEC = 20
DEFAULT_STALL_SEC = 45
DEFAULT_SLOW_WINDOW_SEC = 30
TRANSCODE_POLL_START_SEC = 60
TRANSCODE_POLL_MIN_SEC = 35
TRANSCODE_POLL_STEP_SEC = 5

LogFn = Callable[[str], None]


def _transcode_poll_interval_sec(poll_round: int) -> int:
    """转码轮询间隔：首次 60s，每次减 5s，最低 35s。"""
    interval = TRANSCODE_POLL_START_SEC - poll_round * TRANSCODE_POLL_STEP_SEC
    return max(TRANSCODE_POLL_MIN_SEC, interval)


class BatchLogger:
    """页面运行日志（简洁）与终端开发日志（详细）双通道。"""

    def __init__(self, ui: LogFn, dev: LogFn | None = None) -> None:
        self.ui = ui
        self.dev = dev if dev is not None else print

    def both(self, msg: str) -> None:
        self.ui(msg)
        self.dev(msg)

    def say(self, ui_msg: str, dev_msg: str) -> None:
        self.ui(ui_msg)
        self.dev(dev_msg)

    def dev_only(self, msg: str) -> None:
        self.dev(msg)


class _TranscribePipeline:
    """串行识别队列：解压后立即入队，同一时刻只跑一部剧的识别。"""

    def __init__(self, logger: BatchLogger) -> None:
        self._logger = logger
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="Transcribe")
        self._futures: list[Any] = []

    def submit(self, folder_path: Path, *, label: str | None = None) -> None:
        name = label or folder_path.name
        self._logger.dev_only(f"   📋 已加入识别队列: {name}")
        self._futures.append(
            self._executor.submit(_transcribe_drama_folder, folder_path, self._logger)
        )

    def has_pending(self) -> bool:
        return any(not f.done() for f in self._futures)

    def wait_all(self) -> list[str]:
        if not self._futures:
            self._executor.shutdown(wait=True)
            return []
        self._logger.say("⏳ 等待识别完成…", "\n⏳ 等待识别队列完成…")
        completed: list[str] = []
        for future in self._futures:
            try:
                folder = future.result()
                if folder:
                    completed.append(folder)
            except Exception:
                pass
        self._futures.clear()
        self._executor.shutdown(wait=True)
        self._logger.say("   识别全部完成", "   识别队列已全部处理完毕")
        return completed

    def cancel(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._futures.clear()


@dataclass
class BatchDownloadOptions:
    download_dir: Path | str = DEFAULT_DOWNLOAD_DIR
    skip_done: bool = True
    stop_on_error: bool = False
    create_only: bool = False
    download_only: bool = False
    delay_sec: float = 3
    timeout_min: int = 30
    concurrency: int = DEFAULT_CONCURRENT_DOWNLOADS
    download_timeout_min: int = DEFAULT_DOWNLOAD_TIMEOUT_MIN
    download_retries: int = DEFAULT_DOWNLOAD_RETRIES
    min_speed_kbps: int = DEFAULT_MIN_SPEED_KBPS
    from_ep: int = DEFAULT_FROM_EP
    to_ep: int = DEFAULT_TO_EP
    headless: bool = True
    cancel_check: Callable[[], bool] | None = None
    auto_unzip_and_delete: bool = True
    auto_transcribe: bool = True


@dataclass
class DownloadTargetItem:
    name: str = ""
    from_ep: int | None = None
    to_ep: int | None = None
    task_id: str | None = None
    download_dir: str | None = None
    out: str | None = None
    mode: str = "name"
    extra: dict[str, Any] = field(default_factory=dict)


def _target_key(item: DownloadTargetItem | dict[str, Any], index: int, defaults: dict[str, int]) -> str:
    if isinstance(item, dict):
        if item.get("id"):
            return f"id:{item['id']}"
        from_ep = item.get("from", defaults["from"])
        to_ep = item.get("to", defaults["to"])
        name = item.get("name") or item.get("bookName") or f"item_{index}"
        return f"name:{name}|{from_ep}-{to_ep}"
    if item.task_id:
        return f"id:{item.task_id}"
    from_ep = item.from_ep if item.from_ep is not None else defaults["from"]
    to_ep = item.to_ep if item.to_ep is not None else defaults["to"]
    name = item.name or f"item_{index}"
    return f"name:{name}|{from_ep}-{to_ep}"


def _load_done_set() -> set[str]:
    if not DONE_FILE.is_file():
        return set()
    return {line for line in DONE_FILE.read_text(encoding="utf-8").splitlines() if line}


def _mark_done(key: str) -> None:
    with DONE_FILE.open("a", encoding="utf-8") as f:
        f.write(f"{key}\n")


def _append_log(entry: dict[str, Any]) -> None:
    if not is_dev_runtime():
        return
    ensure_changdu_dirs()
    log: list[dict[str, Any]] = []
    if LOG_FILE.is_file():
        try:
            log = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log = []
    entry = {**entry, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    log.append(entry)
    LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_pending(jobs: list[dict[str, Any]]) -> None:
    ensure_changdu_dirs()
    PENDING_FILE.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_pending() -> list[dict[str, Any]]:
    if not PENDING_FILE.is_file():
        raise FileNotFoundError(f"未找到 {PENDING_FILE}，请先执行「仅创建任务」")
    return json.loads(PENDING_FILE.read_text(encoding="utf-8"))


def _unzip_zip(zip_path: Path, logger: BatchLogger, *, delete_zip: bool) -> Path | None:
    extract_dir = zip_path.parent / zip_path.stem
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
        if delete_zip:
            zip_path.unlink()
            logger.say(
                "   📂 已解压，已删除压缩包",
                f"   📂 已解压至 {extract_dir}，已删除压缩包",
            )
        else:
            logger.say("   📂 已解压", f"   📂 已解压至 {extract_dir}")
        return extract_dir
    except Exception as exc:
        logger.both(f"   ⚠ 解压失败（保留压缩包）: {zip_path.name} — {exc}")
        return None


def _resolve_video_folder(folder_path: Path) -> Path | None:
    """若解压目录根层无视频，尝试进入唯一子目录。"""
    try:
        scan_drama_folder(str(folder_path))
        return folder_path
    except DramaFolderError:
        pass

    subdirs = [p for p in folder_path.iterdir() if p.is_dir()]
    if len(subdirs) == 1:
        try:
            scan_drama_folder(str(subdirs[0]))
            return subdirs[0]
        except DramaFolderError:
            return None
    return None


def _transcribe_drama_folder(folder_path: Path, logger: BatchLogger) -> str | None:
    resolved = _resolve_video_folder(folder_path)
    if resolved is None:
        logger.both(f"   ⚠ 识别跳过: {folder_path.name} 中未找到视频")
        return None

    try:
        scan = scan_drama_folder(str(resolved))
    except DramaFolderError as exc:
        logger.both(f"   ⚠ 识别跳过: {exc}")
        return None

    project = DramaProject(
        id=uuid.uuid4().hex,
        name=scan.name,
        episode_count=scan.episode_count,
        folder_path=scan.folder_path,
        video_files=scan.video_files,
    )
    logger.both(f"   ▶️ 开始识别: {scan.name}（{scan.episode_count} 集）")
    try:
        TranscriptionService.check_environment()
        output_path = TranscriptionService.transcribe(project)
        logger.say("   ✅ 识别完成", f"   ✅ 识别完成: {output_path}")
        return scan.folder_path
    except Exception as exc:
        logger.both(f"   ❌ 识别失败: {exc}")
        return None


def _post_process_downloaded_file(
    file_path: Path,
    opts: BatchDownloadOptions,
    logger: BatchLogger,
    *,
    transcribe_pipeline: _TranscribePipeline | None = None,
    label: str | None = None,
) -> None:
    extract_dir: Path | None = None
    if file_path.suffix.lower() == ".zip":
        need_unzip = opts.auto_unzip_and_delete or opts.auto_transcribe
        if need_unzip:
            extract_dir = _unzip_zip(
                file_path,
                logger,
                delete_zip=opts.auto_unzip_and_delete,
            )
    elif opts.auto_transcribe and file_path.is_dir():
        extract_dir = file_path

    if opts.auto_transcribe:
        if extract_dir is not None:
            if transcribe_pipeline is not None:
                transcribe_pipeline.submit(extract_dir, label=label)
            else:
                _transcribe_drama_folder(extract_dir, logger)
        elif file_path.suffix.lower() == ".zip":
            logger.both("   ⚠ 识别跳过: 压缩包未能解压")


def normalize_targets(
    raw: list[dict[str, Any]], defaults: dict[str, int]
) -> list[dict[str, Any]]:
    if not raw:
        raise ValueError("下载列表不能为空")
    result = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index + 1} 项无效")
        if item.get("id"):
            result.append({**item, "mode": "id"})
            continue
        name = item.get("name") or item.get("bookName")
        if not name:
            raise ValueError(f"第 {index + 1} 项缺少剧名或任务 id")
        result.append(
            {
                **item,
                "name": name,
                "from": item.get("from", defaults["from"]),
                "to": item.get("to", defaults["to"]),
                "mode": "name",
            }
        )
    return result


def _resolve_episode_range(
    client: SeriesListClient,
    item: dict[str, Any],
    defaults: dict[str, int],
) -> dict[str, Any]:
    from_ep = item.get("from", defaults["from"])
    to_ep = item.get("to", defaults["to"])
    book_id = item.get("bookId")
    name = item["name"]

    drama = client.find_drama_by_name(name)
    book_id = book_id or drama.get("book_id")
    name = drama.get("series_name") or name
    episode_amount = drama.get("episode_amount") or to_ep

    if to_ep > episode_amount:
        to_ep = episode_amount
    if to_ep < from_ep:
        raise ValueError(f"无效集数范围: {from_ep}-{to_ep}")

    return {"from": from_ep, "to": to_ep, "bookId": book_id, "name": name}


def phase1_create_tasks(
    client: SeriesListClient,
    targets: list[dict[str, Any]],
    opts: BatchDownloadOptions,
    ep_defaults: dict[str, int],
    done_set: set[str],
    logger: BatchLogger,
) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    summary = {"created": 0, "skip": 0, "fail": 0}

    logger.both("\n========== 阶段 1/2: 批量创建下载任务 ==========\n")

    for i, item in enumerate(targets):
        if opts.cancel_check and opts.cancel_check():
            raise RuntimeError("任务已取消")

        key = _target_key(item, i, ep_defaults)

        if opts.skip_done and key in done_set:
            name = item.get("name") or item.get("bookName") or key
            logger.say(f"[{i + 1}/{len(targets)}] ⏩ 跳过（已下载）: {name}", f"[{i + 1}/{len(targets)}] ⏩ 跳过（已下载）: {key}")
            summary["skip"] += 1
            continue

        try:
            if item.get("mode") == "id":
                task_id = str(item["id"])
                logger.say(
                    f"[{i + 1}/{len(targets)}] 使用已有任务",
                    f"[{i + 1}/{len(targets)}] 使用已有任务: download_id={task_id}",
                )
                jobs.append(
                    {
                        "key": key,
                        "downloadId": task_id,
                        "bookName": None,
                        "name": task_id,
                        "from": None,
                        "to": None,
                        "item": item,
                    }
                )
                summary["created"] += 1
            else:
                resolved = _resolve_episode_range(client, item, ep_defaults)
                from_ep, to_ep = resolved["from"], resolved["to"]
                book_id, name = resolved["bookId"], resolved["name"]
                logger.both(f"[{i + 1}/{len(targets)}] 创建任务: {name} ({from_ep}-{to_ep})")

                created = client.batch_download_in_range(book_id, name, from_ep, to_ep)
                if created.get("code") != 0:
                    raise RuntimeError(
                        f"创建失败: {created.get('message') or json.dumps(created, ensure_ascii=False)}"
                    )

                task_id = str(created["task_id"])
                logger.dev_only(f"   ✅ download_id={task_id}")
                jobs.append(
                    {
                        "key": key,
                        "downloadId": task_id,
                        "bookName": name,
                        "name": name,
                        "from": from_ep,
                        "to": to_ep,
                        "item": item,
                    }
                )
                summary["created"] += 1
        except Exception as exc:
            msg = str(exc)
            logger.both(f"   ❌ {msg}")
            _append_log({"phase": 1, "key": key, "status": "fail", "error": msg, "item": item})
            summary["fail"] += 1
            if opts.stop_on_error:
                raise

        if i < len(targets) - 1 and opts.delay_sec > 0:
            time.sleep(opts.delay_sec)

    _save_pending(jobs)
    logger.both(
        f"\n阶段 1 完成: 创建/登记 {summary['created']} 个，"
        f"跳过 {summary['skip']} 个，失败 {summary['fail']} 个"
    )
    logger.dev_only(f"任务列表已保存: {PENDING_FILE}")
    return jobs


def _prepare_download_job(
    client: SeriesListClient,
    job: dict[str, Any],
    opts: BatchDownloadOptions,
) -> dict[str, Any]:
    """在 Playwright 线程准备下载元数据（查询任务 + 获取 URL）。"""
    item = job.get("item") or {}
    prepared = client.prepare_task_zip_download(
        job["downloadId"],
        download_dir=item.get("downloadDir") or opts.download_dir,
        dest_path=item.get("out"),
    )
    return {**prepared, "job": job}


def _download_prepared_with_retry(
    client: SeriesListClient,
    prepared: dict[str, Any],
    opts: BatchDownloadOptions,
    dl_opts: dict[str, Any],
) -> dict[str, Any]:
    """在线程池中仅执行 requests 流式下载（不触碰 Playwright page）。"""
    last_err: Exception | None = None
    for attempt in range(1, opts.download_retries + 1):
        try:
            dl_stats = client.download_zip_from_url(
                prepared["downloadUrl"],
                prepared["destPath"],
                timeout_ms=dl_opts["download_timeout_ms"],
                min_speed_kbps=dl_opts["min_speed_kbps"],
                warmup_sec=dl_opts["warmup_sec"],
                stall_sec=dl_opts["stall_sec"],
                slow_window_sec=dl_opts["slow_window_sec"],
                cancel_check=opts.cancel_check,
            )
            return {
                "downloadId": prepared["downloadId"],
                "bookName": prepared["bookName"],
                "taskName": prepared["taskName"],
                "filePath": dl_stats["filePath"],
                "downloadUrl": prepared["downloadUrl"],
                "avgSpeedKbps": dl_stats["avgSpeedKbps"],
                "elapsedSec": dl_stats["elapsedSec"],
            }
        except Exception as exc:
            last_err = exc
            if attempt < opts.download_retries:
                time.sleep(2)
    assert last_err is not None
    raise last_err


def phase2_download_files(
    client: SeriesListClient,
    jobs: list[dict[str, Any]],
    opts: BatchDownloadOptions,
    done_set: set[str],
    logger: BatchLogger,
) -> dict[str, int]:
    summary = {"success": 0, "skip": 0, "fail": 0}
    dl_opts = {
        "concurrency": opts.concurrency,
        "download_timeout_ms": opts.download_timeout_min * 60 * 1000,
        "min_speed_kbps": opts.min_speed_kbps,
        "warmup_sec": DEFAULT_WARMUP_SEC,
        "stall_sec": DEFAULT_STALL_SEC,
        "slow_window_sec": DEFAULT_SLOW_WINDOW_SEC,
    }
    pending = [j for j in jobs if not (opts.skip_done and done_set and j["key"] in done_set)]

    if not pending:
        logger.both("\n没有待下载任务")
        return summary

    logger.both("\n========== 阶段 2/2: 等待转码并并行下载 ==========\n")
    logger.say(
        f"待下载 {len(pending)} 个",
        f"待下载 {len(pending)} 个 | 并行 {dl_opts['concurrency']} | "
        f"慢速阈值 {dl_opts['min_speed_kbps']} KB/s | "
        f"最多尝试 {opts.download_retries} 次",
    )
    logger.dev_only(
        f"转码轮询 {TRANSCODE_POLL_START_SEC}s 起每次 -{TRANSCODE_POLL_STEP_SEC}s，"
        f"最低 {TRANSCODE_POLL_MIN_SEC}s；转码超时 {opts.timeout_min} 分钟，"
        f"下载总超时兜底 {opts.download_timeout_min} 分钟"
    )

    transcoding = {j["downloadId"]: j for j in pending}
    transcode_deadlines = {
        j["downloadId"]: time.time() + opts.timeout_min * 60 for j in pending
    }
    queued: set[str] = set()
    download_queue: list[dict[str, Any]] = []
    transcode_poll_round = 0
    transcribe_pipeline = _TranscribePipeline(logger) if opts.auto_transcribe else None

    def process_download(prepared: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        job = prepared["job"]
        label = job.get("bookName") or job.get("name")
        try:
            result = _download_prepared_with_retry(client, prepared, opts, dl_opts)
            return "ok", {"job": job, "label": label, "result": result}
        except Exception as exc:
            return "fail", {"job": job, "label": label, "error": str(exc)}

    try:
        with ThreadPoolExecutor(max_workers=opts.concurrency) as executor:
            futures: dict[Any, dict[str, Any]] = {}

            while (
                transcoding
                or futures
                or download_queue
                or (transcribe_pipeline is not None and transcribe_pipeline.has_pending())
            ):
                if opts.cancel_check and opts.cancel_check():
                    if transcribe_pipeline is not None:
                        transcribe_pipeline.cancel()
                    raise RuntimeError("任务已取消")

                for download_id in list(transcoding.keys()):
                    job = transcoding[download_id]
                    if time.time() > transcode_deadlines[download_id]:
                        label = job.get("bookName") or job.get("name")
                        logger.say(
                            f"❌ 转码超时: {label}",
                            f"❌ 转码超时: {label} ({download_id})",
                        )
                        _append_log(
                            {
                                "phase": 2,
                                "key": job["key"],
                                "status": "fail",
                                "error": "转码超时",
                                "downloadId": download_id,
                            }
                        )
                        transcoding.pop(download_id)
                        summary["fail"] += 1
                        continue

                    try:
                        task = client.find_download_task(download_id)
                    except Exception as exc:
                        logger.dev_only(f"   ⚠ 查询失败 {download_id}: {exc}")
                        continue

                    if not task:
                        continue

                    if task.get("task_status") == 3:
                        label = task.get("book_name") or job.get("name")
                        logger.say(
                            f"❌ 转码失败: {label}",
                            f"❌ 转码失败: {label} ({download_id})",
                        )
                        _append_log(
                            {
                                "phase": 2,
                                "key": job["key"],
                                "status": "fail",
                                "error": "转码失败",
                                "downloadId": download_id,
                            }
                        )
                        transcoding.pop(download_id)
                        summary["fail"] += 1
                        continue

                    if task.get("task_status") == DOWNLOAD_TASK_STATUS_DONE and download_id not in queued:
                        transcoding.pop(download_id)
                        queued.add(download_id)
                        job["bookName"] = task.get("book_name") or job.get("bookName")
                        download_queue.append(job)
                        logger.both(f"   ✓ 转码完成: {job.get('bookName') or job.get('name')}")

                while download_queue and len(futures) < opts.concurrency:
                    job = download_queue.pop(0)
                    label = job.get("bookName") or job.get("name")
                    try:
                        prepared = _prepare_download_job(client, job, opts)
                    except Exception as exc:
                        msg = str(exc)
                        logger.both(f"   ❌ {label} 准备下载失败: {msg}")
                        _append_log(
                            {
                                "phase": 2,
                                "key": job["key"],
                                "status": "fail",
                                "error": msg,
                                "downloadId": job["downloadId"],
                            }
                        )
                        summary["fail"] += 1
                        if opts.stop_on_error:
                            raise RuntimeError(msg)
                        continue
                    logger.say(
                        f"\n📥 开始下载: {label}",
                        f"\n📥 开始下载: {label} (并行 {len(futures) + 1}/{opts.concurrency})",
                    )
                    future = executor.submit(process_download, prepared)
                    futures[future] = job

                done_futures = [f for f in list(futures.keys()) if f.done()]
                for future in done_futures:
                    job = futures.pop(future)
                    status, payload = future.result()
                    if status == "ok":
                        result = payload["result"]
                        label = payload["label"]
                        file_path = Path(result["filePath"])
                        size_mb = file_path.stat().st_size / 1024 / 1024
                        speed_info = ""
                        if result.get("avgSpeedKbps") is not None:
                            speed_info = (
                                f"，均速 {result['avgSpeedKbps']} KB/s，"
                                f"耗时 {result.get('elapsedSec')}s"
                            )
                        ui_speed = f" ({size_mb:.2f} MB)" if size_mb else ""
                        dev_speed = f" ({size_mb:.2f} MB{speed_info})"
                        logger.say(
                            f"   ✅ {label} 下载完成{ui_speed}",
                            f"   ✅ {label} → {result['filePath']}{dev_speed}",
                        )
                        _post_process_downloaded_file(
                            file_path,
                            opts,
                            logger,
                            transcribe_pipeline=transcribe_pipeline,
                            label=label,
                        )
                        _mark_done(job["key"])
                        done_set.add(job["key"])
                        _append_log(
                            {
                                "phase": 2,
                                "key": job["key"],
                                "status": "success",
                                "downloadId": job["downloadId"],
                                "bookName": result.get("bookName"),
                                "filePath": result["filePath"],
                                "from": job.get("from"),
                                "to": job.get("to"),
                            }
                        )
                        summary["success"] += 1
                    else:
                        label = payload["label"]
                        msg = payload["error"]
                        logger.both(f"   ❌ {label} 下载失败: {msg}")
                        _append_log(
                            {
                                "phase": 2,
                                "key": job["key"],
                                "status": "fail",
                                "error": msg,
                                "downloadId": job["downloadId"],
                            }
                        )
                        summary["fail"] += 1
                        if opts.stop_on_error:
                            raise RuntimeError(msg)

                if transcoding:
                    waiting = "、".join(j.get("bookName") or j.get("name") for j in transcoding.values())
                    poll_sec = _transcode_poll_interval_sec(transcode_poll_round)
                    logger.both(f"\n⏳ 转码中 {len(transcoding)} 个: {waiting}（{poll_sec}s 后再次查询）")
                    time.sleep(poll_sec)
                    transcode_poll_round += 1
                elif futures or download_queue:
                    time.sleep(0.5)
                elif transcribe_pipeline is not None and transcribe_pipeline.has_pending():
                    time.sleep(0.5)
    finally:
        if transcribe_pipeline is not None:
            summary["transcribed_folders"] = transcribe_pipeline.wait_all()

    return summary


def run_batch_download(
    targets: list[dict[str, Any]],
    opts: BatchDownloadOptions | None = None,
    log: LogFn | None = None,
    dev_log: LogFn | None = None,
) -> dict[str, Any]:
    """执行完整或分阶段批量下载，返回汇总信息。"""
    opts = opts or BatchDownloadOptions()
    logger = BatchLogger(log or print, dev_log or print)
    ensure_changdu_dirs()

    ep_defaults = {"from": opts.from_ep, "to": opts.to_ep}
    done_set = _load_done_set() if opts.skip_done else set()

    with SeriesListClient(headless=opts.headless) as client:
        logger.both("初始化客户端...")
        logger.say(
            f"应用: {client.app_info['app_name']}",
            f"应用: {client.app_info['app_name']} | distributor={client.app_info['distributor_id']}",
        )
        logger.dev_only(f"默认集数: {ep_defaults['from']}-{ep_defaults['to']}")

        if opts.download_only:
            jobs = _load_pending()
            logger.both(f"\n从缓存加载 {len(jobs)} 个待下载任务")
        else:
            normalized = normalize_targets(targets, ep_defaults)
            logger.both(f"共 {len(normalized)} 个下载目标")
            jobs = phase1_create_tasks(client, normalized, opts, ep_defaults, done_set, logger)

        summary2 = {"success": 0, "skip": 0, "fail": 0}
        if not opts.create_only:
            summary2 = phase2_download_files(client, jobs, opts, done_set, logger)

    logger.both("\n" + "=" * 50)
    logger.both("批量创建完成（未下载）" if opts.create_only else "批量下载完成")
    if not opts.create_only:
        logger.both(f"  ✅ 下载成功: {summary2['success']}")
        logger.both(f"  ❌ 失败/超时: {summary2['fail']}")
    if is_dev_runtime():
        logger.dev_only(f"  日志: {LOG_FILE}")
    logger.dev_only(f"  进度: {DONE_FILE}")

    return {
        "phase2": summary2,
        "jobs": jobs,
        "transcribed_folders": summary2.get("transcribed_folders", []),
    }
