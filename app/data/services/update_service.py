"""客户端更新检查与提示。"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

import requests
from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QProgressDialog, QWidget
from qfluentwidgets import Dialog, qconfig

from app.common.config import APP_NAME, VERSION, cfg
from app.common.version_utils import is_version_older
from app.core.task_manager import task_manager
from app.data.api.api import ApiError, get_api


@dataclass(frozen=True)
class UpdateInfo:
    latest: str
    min_supported: str
    download_url: str
    changelog: str
    force: bool


class _DownloadProgressBridge(QObject):
    progress = Signal(int, int)  # downloaded, total


def fetch_update_info() -> UpdateInfo | None:
    api = get_api()
    data = api.fetch_client_version()
    latest = (data.get("latest") or "").strip()
    if not latest or not is_version_older(VERSION, latest):
        return None

    min_supported = (data.get("min_supported") or latest).strip()
    download_url = (data.get("download_url") or "").strip()
    if download_url.startswith("/"):
        download_url = f"{api.base_url}{download_url}"
    changelog = (data.get("changelog") or "").strip()
    force = is_version_older(VERSION, min_supported)
    return UpdateInfo(
        latest=latest,
        min_supported=min_supported,
        download_url=download_url,
        changelog=changelog,
        force=force,
    )


def should_prompt_update(info: UpdateInfo) -> bool:
    if info.force:
        return True
    dismissed = (cfg.update_dismissed_version.value or "").strip()
    return dismissed != info.latest


def _installer_filename(url: str, version: str) -> str:
    path = unquote(urlparse(url).path or "")
    name = Path(path).name
    if name.lower().endswith(".exe") and name.strip():
        safe = re.sub(r'[<>:"/\\|?*]', "_", name)
        return safe
    return f"{APP_NAME}-v{version}-installer.exe"


def download_update_installer(
    url: str,
    *,
    version: str,
    progress_callback: Callable[[int, int], None] | None = None,
) -> Path:
    """从直链下载安装包到系统临时目录，返回本地路径。"""
    url = (url or "").strip()
    if not url:
        raise ValueError("未配置安装包下载地址")

    dest_dir = Path(tempfile.gettempdir()) / "AutomatedEditUpdate"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / _installer_filename(url, version)
    part = dest.with_suffix(dest.suffix + ".part")

    with requests.get(url, stream=True, timeout=(30, 600)) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("content-length") or 0)
        downloaded = 0
        with open(part, "wb") as f:
            for chunk in resp.iter_content(chunk_size=256 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded, total)

    if dest.exists():
        dest.unlink()
    part.replace(dest)
    return dest


def _launch_installer(path: Path) -> None:
    local = str(path.resolve())
    try:
        os.startfile(local)  # type: ignore[attr-defined]
    except Exception:
        QDesktopServices.openUrl(QUrl.fromLocalFile(local))


def _build_message(info: UpdateInfo) -> str:
    lines = [
        f"发现新版本 {info.latest}（当前 {VERSION}）。",
    ]
    if info.force:
        lines.append("当前版本已不受支持，请升级后继续使用。")
    if info.changelog:
        lines.append("")
        lines.append(info.changelog)
    if info.download_url:
        lines.append("")
        lines.append("是否立即下载并安装新版本？")
        lines.append("下载完成后会自动打开安装程序；安装前请先关闭本程序。")
    else:
        lines.append("")
        lines.append("请联系管理员获取安装包。")
    return "\n".join(lines)


def _start_installer_download(parent: QWidget | None, info: UpdateInfo) -> None:
    from app.common.utils import show_dialog, show_info_bar

    if not info.download_url:
        show_dialog(parent, "未配置安装包下载地址，请联系管理员。")
        return

    progress = QProgressDialog("正在下载安装包…", None, 0, 100, parent)
    progress.setWindowTitle("下载更新")
    progress.setCancelButton(None)
    progress.setMinimumDuration(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    progress.setValue(0)
    progress.show()

    bridge = _DownloadProgressBridge(progress)

    def _on_progress(downloaded: int, total: int) -> None:
        if total > 0:
            progress.setMaximum(100)
            progress.setValue(min(100, int(downloaded * 100 / total)))
            mb_d = downloaded / (1024 * 1024)
            mb_t = total / (1024 * 1024)
            progress.setLabelText(f"正在下载安装包… {mb_d:.1f}/{mb_t:.1f} MB")
        else:
            progress.setMaximum(0)
            progress.setLabelText(
                f"正在下载安装包… {downloaded / (1024 * 1024):.1f} MB"
            )

    bridge.progress.connect(_on_progress)

    def _do():
        return download_update_installer(
            info.download_url,
            version=info.latest,
            progress_callback=lambda d, t: bridge.progress.emit(d, t),
        )

    def _on_success(path: Path):
        progress.close()
        progress.deleteLater()
        try:
            _launch_installer(path)
        except Exception as exc:
            show_dialog(parent, f"安装包已下载，但无法自动打开：{exc}\n路径：{path}")
            return
        show_dialog(
            parent,
            "安装包已下载并打开安装程序。\n请先关闭本软件，再按安装向导完成更新。",
            title="下载完成",
        )

    def _on_error(msg: str):
        progress.close()
        progress.deleteLater()
        show_dialog(parent, f"下载安装包失败：{msg}")
        show_info_bar(parent, "下载失败", level="error")

    task_manager.submit_task(_do, on_success=_on_success, on_error=_on_error)


def show_update_dialog(parent: QWidget | None, info: UpdateInfo) -> None:
    dialog = Dialog("发现新版本", _build_message(info), parent)
    dialog.contentLabel.setWordWrap(True)
    dialog.yesButton.setText("立即更新")
    if info.force or not info.download_url:
        dialog.cancelButton.hide()
        dialog.yesButton.setEnabled(bool(info.download_url))
        if not info.download_url:
            dialog.yesButton.setText("确定")
    else:
        dialog.cancelButton.setText("稍后")

    if dialog.exec():
        if info.download_url:
            _start_installer_download(parent, info)
    elif not info.force:
        qconfig.set(cfg.update_dismissed_version, info.latest)


def _handle_check_result(
    parent: QWidget | None,
    *,
    manual: bool,
    status: str,
    info: UpdateInfo | None,
    error_message: str | None,
) -> None:
    if status == "error":
        if manual:
            from app.common.utils import show_dialog

            show_dialog(parent, error_message or "检查更新失败，请稍后重试。")
        return

    if info is None:
        if manual:
            from app.common.utils import show_dialog

            show_dialog(parent, f"当前已是最新版本（{VERSION}）。")
        return

    if manual or should_prompt_update(info):
        show_update_dialog(parent, info)


def check_and_prompt_update(parent: QWidget | None = None, *, manual: bool = False) -> None:
    """异步检查更新；网络在后台，弹窗在主线程。"""

    def _do():
        try:
            return ("ok", fetch_update_info(), None)
        except ApiError as exc:
            msg = f"检查更新失败：{exc}" if manual else None
            return ("error", None, msg)
        except Exception:
            return ("error", None, "检查更新失败，请稍后重试。" if manual else None)

    def _on_success(result):
        status, info, error_message = result
        _handle_check_result(
            parent, manual=manual, status=status, info=info, error_message=error_message
        )

    def _on_error(msg: str):
        if not manual:
            return
        from app.common.utils import show_dialog

        show_dialog(parent, msg or "检查更新失败，请稍后重试。")

    # 检查更新必须跳过封禁闸：被 block 时否则任务直接失败且原先无 on_error，表现为「点了没反应」
    task_manager.submit_task(
        _do,
        on_success=_on_success,
        on_error=_on_error,
        check_access=False,
    )


def prompt_update_on_startup(parent: QWidget | None = None) -> None:
    check_and_prompt_update(parent, manual=False)
