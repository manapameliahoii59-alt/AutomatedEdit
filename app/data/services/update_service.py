"""客户端更新检查与提示。"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse

import requests
from PySide6.QtCore import QObject, Qt, QUrl, Signal, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
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
    from app.common.utils import show_dialog, show_toast
    from shiboken6 import isValid

    if not info.download_url:
        show_dialog(parent, "未配置安装包下载地址，请联系管理员。")
        return

    host = parent.window() if parent is not None else parent
    progress = QProgressDialog("正在下载安装包…", None, 0, 100, host)
    progress.setWindowTitle(f"下载更新 {info.latest}")
    progress.setCancelButton(None)
    progress.setMinimumDuration(0)
    progress.setAutoClose(False)
    progress.setAutoReset(False)
    progress.setMinimumWidth(360)
    progress.setValue(0)
    progress.setWindowModality(Qt.WindowModality.ApplicationModal)
    progress.show()
    progress.raise_()
    progress.activateWindow()

    bridge = _DownloadProgressBridge(progress)

    def _on_progress(downloaded: int, total: int) -> None:
        if not isValid(progress):
            return
        if total > 0:
            progress.setMaximum(100)
            pct = min(100, int(downloaded * 100 / total))
            progress.setValue(pct)
            mb_d = downloaded / (1024 * 1024)
            mb_t = total / (1024 * 1024)
            progress.setLabelText(
                f"正在下载 {info.latest}… {mb_d:.1f}/{mb_t:.1f} MB（{pct}%）"
            )
        else:
            progress.setMaximum(0)
            progress.setLabelText(
                f"正在下载 {info.latest}… {downloaded / (1024 * 1024):.1f} MB"
            )

    bridge.progress.connect(_on_progress)

    def _do():
        return download_update_installer(
            info.download_url,
            version=info.latest,
            progress_callback=lambda d, t: bridge.progress.emit(d, t),
        )

    def _close_progress() -> None:
        if isValid(progress):
            progress.close()
            progress.deleteLater()

    def _on_success(path: Path):
        _close_progress()
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
        _close_progress()
        show_dialog(parent, f"下载安装包失败：{msg}")
        show_toast(parent, "下载失败", level="error")

    task_manager.submit_task(
        _do,
        on_success=_on_success,
        on_error=_on_error,
        check_access=False,
    )


class ForcedUpdateDialog(QDialog):
    """强制更新模态对话框：
    - 绝不允许通过 ESC 或点击关闭按钮绕过使用！
    - 若用户主动关闭或退出，直接终止程序进程 (sys.exit(0))。
    """

    def __init__(self, info: UpdateInfo, parent: QWidget | None = None):
        super().__init__(parent)
        self.info = info
        self._is_installing = False
        self._init_ui()

    def _init_ui(self):
        self.setWindowTitle("版本停用通知 - 必须更新")
        self.setFixedWidth(480)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title_label = QLabel("⚠️ 当前版本已停用，必须更新后方可使用")
        title_label.setStyleSheet("font-size: 16px; font-weight: bold; color: #cf1322;")
        layout.addWidget(title_label)

        desc_text = (
            f"当前客户端版本：v{VERSION}\n"
            f"系统最低支持版本：v{self.info.min_supported}\n"
            f"最新发布版本：v{self.info.latest}\n\n"
            "为保障系统稳定与数据一致性，您当前的版本已停止服务。请更新至最新版本以继续使用。"
        )
        desc_label = QLabel(desc_text)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("font-size: 13px; color: #262626; line-height: 1.5;")
        layout.addWidget(desc_label)

        if self.info.changelog:
            cl_title = QLabel("更新说明：")
            cl_title.setStyleSheet("font-size: 12px; font-weight: bold; color: #595959;")
            layout.addWidget(cl_title)

            cl_box = QTextEdit()
            cl_box.setReadOnly(True)
            cl_box.setPlainText(self.info.changelog)
            cl_box.setFixedHeight(90)
            cl_box.setStyleSheet(
                "background: #f5f5f5; border: 1px solid #d9d9d9; border-radius: 4px; padding: 6px; font-size: 12px; color: #595959;"
            )
            layout.addWidget(cl_box)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #f0f0f0;
                border-radius: 6px;
            }
            QProgressBar::chunk {
                background-color: #1890ff;
                border-radius: 6px;
            }
        """)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 12px; color: #8c8c8c;")
        self.status_label.hide()
        layout.addWidget(self.status_label)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        btn_layout.addStretch()

        self.exit_btn = QPushButton("退出软件")
        self.exit_btn.setStyleSheet(
            "padding: 7px 18px; font-size: 13px; border-radius: 4px; border: 1px solid #d9d9d9; background: #fff;"
        )
        self.exit_btn.clicked.connect(self._do_exit)
        btn_layout.addWidget(self.exit_btn)

        if self.info.download_url:
            self.update_btn = QPushButton("立即下载并更新")
            self.update_btn.setStyleSheet(
                "padding: 7px 22px; font-size: 13px; font-weight: bold; border-radius: 4px; border: none; background: #1890ff; color: #fff;"
            )
            self.update_btn.clicked.connect(self._do_update)
            btn_layout.addWidget(self.update_btn)
        else:
            tip = QLabel("未配置下载链接，请联系管理员获取安装包")
            tip.setStyleSheet("font-size: 12px; color: #ff4d4f;")
            btn_layout.insertWidget(0, tip)

        layout.addLayout(btn_layout)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            event.ignore()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if not self._is_installing:
            sys.exit(0)
        event.accept()

    def _do_exit(self):
        sys.exit(0)

    def _do_update(self):
        if not self.info.download_url:
            return
        self.update_btn.setEnabled(False)
        self.update_btn.setText("正在下载…")
        self.exit_btn.setEnabled(False)
        self.progress_bar.show()
        self.status_label.show()
        self.status_label.setText("正在准备连接服务器下载安装包…")

        bridge = _DownloadProgressBridge(self)

        def _on_progress(d: int, t: int):
            if t > 0:
                pct = min(100, int(d * 100 / t))
                self.progress_bar.setMaximum(100)
                self.progress_bar.setValue(pct)
                self.status_label.setText(
                    f"下载中: {d / (1024*1024):.1f} / {t / (1024*1024):.1f} MB ({pct}%)"
                )
            else:
                self.progress_bar.setMaximum(0)
                self.status_label.setText(f"已下载: {d / (1024*1024):.1f} MB")

        bridge.progress.connect(_on_progress)

        def _worker():
            return download_update_installer(
                self.info.download_url,
                version=self.info.latest,
                progress_callback=lambda d, t: bridge.progress.emit(d, t),
            )

        def _on_success(path: Path):
            self._is_installing = True
            self.status_label.setText("下载完成，正在启动安装程序…")
            try:
                _launch_installer(path)
            except Exception as e:
                self.status_label.setText(f"无法自动打开安装程序，请手动安装：{path}")
                self.update_btn.setEnabled(True)
                self.update_btn.setText("重试更新")
                self.exit_btn.setEnabled(True)
                return
            QTimer.singleShot(1000, lambda: sys.exit(0))

        def _on_error(err_msg: str):
            self.status_label.setText(f"下载失败：{err_msg}")
            self.status_label.setStyleSheet("font-size: 12px; color: #ff4d4f;")
            self.update_btn.setEnabled(True)
            self.update_btn.setText("重试下载")
            self.exit_btn.setEnabled(True)

        task_manager.submit_task(
            _worker,
            on_success=_on_success,
            on_error=_on_error,
            check_access=False,
        )


def show_update_dialog(parent: QWidget | None, info: UpdateInfo) -> None:
    if info.force:
        dialog = ForcedUpdateDialog(info, parent)
        dialog.exec()
        sys.exit(0)
        return

    dialog = Dialog("发现新版本", _build_message(info), parent)
    dialog.contentLabel.setWordWrap(True)
    dialog.yesButton.setText("立即更新")
    if not info.download_url:
        dialog.cancelButton.hide()
        dialog.yesButton.setEnabled(False)
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


def check_and_prompt_update(
    parent: QWidget | None = None,
    *,
    manual: bool = False,
    on_busy: Callable[[bool], None] | None = None,
) -> None:
    """异步检查更新；网络在后台，弹窗在主线程。

    manual=True 时显示顶部加载条；on_busy(True/False) 供设置页禁用「检查更新」按钮。
    """
    from shiboken6 import isValid

    loading_bar = None
    if manual and parent is not None:
        from app.ui.components.bar import ProgressInfoBar

        host = parent.window() if hasattr(parent, "window") else parent
        loading_bar = ProgressInfoBar("检查更新", "正在检查是否有新版本…", host)
        loading_bar.show()

    if on_busy is not None:
        on_busy(True)

    def _finish_busy() -> None:
        if loading_bar is not None and isValid(loading_bar):
            loading_bar.close()
            loading_bar.deleteLater()
        if on_busy is not None:
            on_busy(False)

    def _do():
        try:
            return ("ok", fetch_update_info(), None)
        except ApiError as exc:
            msg = f"检查更新失败：{exc}" if manual else None
            return ("error", None, msg)
        except Exception:
            return ("error", None, "检查更新失败，请稍后重试。" if manual else None)

    def _on_success(result):
        _finish_busy()
        status, info, error_message = result
        _handle_check_result(
            parent, manual=manual, status=status, info=info, error_message=error_message
        )

    def _on_error(msg: str):
        _finish_busy()
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


def check_mandatory_update_on_startup(
    parent: QWidget | None = None,
    on_blocked: Callable[[], None] | None = None,
) -> bool:
    """启动阶段前置检查强制更新。
    若存在强制更新，先调用 on_blocked 回调（如关闭 splash），然后弹出不可绕过的 ForcedUpdateDialog；
    对话框关闭或退出即直接终止应用。
    返回 True 表示触发了强更阻断；返回 False 表示可正常继续启动。
    """
    try:
        info = fetch_update_info()
    except Exception:
        return False

    if info is not None and info.force:
        if on_blocked:
            try:
                on_blocked()
            except Exception:
                pass
        dialog = ForcedUpdateDialog(info, parent)
        dialog.exec()
        sys.exit(0)
        return True
    return False

