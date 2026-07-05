import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import Signal
from qfluentwidgets import qconfig

from app.common.config import cfg
from app.core.playwright_worker import playwright_worker
from app.core.task_manager import task_manager
from app.core.view_model import ViewModel
from app.data.services.batch_download_service import BatchDownloadOptions, run_batch_download
from app.data.services.changdu_login_service import (
    get_changdu_credentials,
    is_auth_file_present,
    run_changdu_login,
)
from app.data.services.changdu_paths import resolve_video_download_root
from app.data.services.series_list_client import SeriesListClient

MAX_DOWNLOAD_EPISODE = 15


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
    authStatusChanged = Signal(bool, str)
    messageReceived = Signal(str)
    errorOccurred = Signal(str)
    clipHandoffRequested = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._targets: list[VideoDownloadTarget] = []
        self._active_tasks = 0
        self._cancel_requested = False
        self._default_from = 1
        self._default_to = 10
        self.targetsChanged.emit(self._targets)

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

    def _refresh_auth_status(self) -> None:
        if is_auth_file_present():
            self.authStatusChanged.emit(True, "已保存登录态（auth.json）")
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
        self._active_tasks -= 1
        if self._active_tasks == 0:
            self.loadingChanged.emit(False, "", "")

    def request_cancel(self) -> None:
        self._cancel_requested = True
        self._append_log("正在取消…")

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
            self.messageReceived.emit(f"登录成功，状态已保存至：{path}")

        def _on_error(msg: str):
            self._remove_task()
            self.errorOccurred.emit(f"登录失败：{msg}")

        task_manager.submit_task(_do_login, on_success=_on_success, on_error=_on_error)

    def check_auth(self) -> None:
        if not is_auth_file_present():
            self.errorOccurred.emit("请先登录常读平台")
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
            else:
                self.authStatusChanged.emit(False, "登录已过期")
                self.errorOccurred.emit(
                    f"登录态无效：{result.get('message') or result.get('code')}"
                )

        def _on_error(msg: str):
            self._remove_task()
            self.authStatusChanged.emit(False, "登录已过期")
            self.errorOccurred.emit(f"验证失败：{msg}")

        task_manager.submit_task(_do_check, on_success=_on_success, on_error=_on_error)

    def add_target(self, name: str, from_ep: int | None = None, to_ep: int | None = None) -> None:
        name = name.strip()
        if not name:
            self.errorOccurred.emit("剧名不能为空")
            return
        target = VideoDownloadTarget(
            id=uuid.uuid4().hex,
            name=name,
            from_ep=from_ep if from_ep is not None else self._default_from,
            to_ep=to_ep if to_ep is not None else self._default_to,
        )
        self._targets.append(target)
        self.targetsChanged.emit(self._targets)

    def add_targets_from_text(self, text: str) -> int:
        names = [line.strip() for line in text.splitlines() if line.strip()]
        if not names:
            self.errorOccurred.emit("请至少输入一个剧名（每行一个）")
            return 0
        for name in names:
            self._targets.append(
                VideoDownloadTarget(
                    id=uuid.uuid4().hex,
                    name=name,
                    from_ep=self._default_from,
                    to_ep=self._default_to,
                )
            )
        self.targetsChanged.emit(self._targets)
        return len(names)

    def remove_target(self, target_id: str) -> None:
        self._targets = [t for t in self._targets if t.id != target_id]
        self.targetsChanged.emit(self._targets)

    def import_targets_json(self, file_path: str) -> None:
        try:
            raw = json.loads(Path(file_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.errorOccurred.emit(f"读取 JSON 失败：{exc}")
            return
        if not isinstance(raw, list):
            self.errorOccurred.emit("JSON 须为非空数组")
            return

        added = 0
        for item in raw:
            if not isinstance(item, dict):
                continue
            if item.get("id"):
                self._targets.append(
                    VideoDownloadTarget(
                        id=uuid.uuid4().hex,
                        name=str(item["id"]),
                        from_ep=self._default_from,
                        to_ep=self._default_to,
                        status="待下载",
                        extra={"task_id": str(item["id"]), "mode": "id"},
                    )
                )
                added += 1
                continue
            name = item.get("name") or item.get("bookName")
            if not name:
                continue
            self._targets.append(
                VideoDownloadTarget(
                    id=uuid.uuid4().hex,
                    name=str(name),
                    from_ep=int(item.get("from", self._default_from)),
                    to_ep=int(item.get("to", self._default_to)),
                    status="待下载",
                )
            )
            added += 1

        if added == 0:
            self.errorOccurred.emit("未从 JSON 中解析到有效剧目")
            return
        self.targetsChanged.emit(self._targets)
        self.messageReceived.emit(f"已从 JSON 导入 {added} 个剧目")

    def _targets_to_payload(self) -> list[dict]:
        payload = []
        for t in self._targets:
            if t.extra.get("mode") == "id" or t.extra.get("task_id"):
                payload.append({"id": t.extra.get("task_id") or t.name})
            else:
                payload.append({"name": t.name, "from": t.from_ep, "to": t.to_ep})
        return payload

    def _set_all_status(self, status: str) -> None:
        for t in self._targets:
            t.status = status
        self.targetsChanged.emit(self._targets)

    def start_download(self, *, create_only: bool = False, download_only: bool = False) -> None:
        if not is_auth_file_present():
            self.errorOccurred.emit("请先登录常读平台")
            return
        if not download_only and not self._targets:
            self.errorOccurred.emit("请先添加下载剧目")
            return
        if self._active_tasks > 0:
            self.messageReceived.emit("当前有任务进行中，请稍候")
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
            auto_transcribe=cfg.video_download_auto_transcribe.value,
        )

        def _do_download():
            def ui_log(line: str):
                self._append_log(line)

            def _run():
                return run_batch_download(targets_payload, opts, log=ui_log, dev_log=print)

            return playwright_worker.run(_run)

        def _on_success(_result: dict):
            self._remove_task()
            for t in self._targets:
                t.status = "已完成" if not create_only else "已创建"
            self.targetsChanged.emit(self._targets)
            if create_only:
                self.messageReceived.emit("下载任务已创建，可稍后点击「继续下载」")
            else:
                self.messageReceived.emit("批量下载流程已结束，详见下方日志")
                folders = _result.get("transcribed_folders") or []
                if cfg.video_download_auto_import_clip.value and folders:
                    self.clipHandoffRequested.emit(folders)

        def _on_error(msg: str):
            self._remove_task()
            for t in self._targets:
                if t.status == "处理中" or t.status == "创建任务中":
                    t.status = "失败"
            self.targetsChanged.emit(self._targets)
            self._append_log(f"❌ {msg}")
            self.errorOccurred.emit(msg)

        task_manager.submit_task(_do_download, on_success=_on_success, on_error=_on_error)

    def set_download_dir(self, path: str) -> None:
        cfg.video_download_dir.value = path.strip()
        qconfig.save()
