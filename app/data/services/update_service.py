"""客户端更新检查与提示。"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget
from qfluentwidgets import Dialog, qconfig

from app.common.config import VERSION, cfg
from app.common.version_utils import is_version_older
from app.data.api.api import ApiError, get_api


@dataclass(frozen=True)
class UpdateInfo:
    latest: str
    min_supported: str
    download_url: str
    changelog: str
    force: bool


def fetch_update_info() -> UpdateInfo | None:
    data = get_api().fetch_client_version()
    latest = (data.get("latest") or "").strip()
    if not latest or not is_version_older(VERSION, latest):
        return None

    min_supported = (data.get("min_supported") or latest).strip()
    download_url = (data.get("download_url") or "").strip()
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
        lines.append("点击「立即下载」将在浏览器中打开安装包。")
        lines.append("安装前请先关闭本程序；安装程序会自动识别您原来的安装路径。")
    else:
        lines.append("")
        lines.append("请联系管理员获取安装包。")
    return "\n".join(lines)


def show_update_dialog(parent: QWidget | None, info: UpdateInfo) -> None:
    dialog = Dialog("发现新版本", _build_message(info), parent)
    dialog.contentLabel.setWordWrap(True)
    dialog.yesButton.setText("立即下载")
    if info.force or not info.download_url:
        dialog.cancelButton.hide()
        dialog.yesButton.setEnabled(bool(info.download_url))
        if not info.download_url:
            dialog.yesButton.setText("确定")
    else:
        dialog.cancelButton.setText("稍后")

    if dialog.exec():
        if info.download_url:
            QDesktopServices.openUrl(QUrl(info.download_url))
    elif not info.force:
        qconfig.set(cfg.update_dismissed_version, info.latest)


def check_and_prompt_update(parent: QWidget | None = None, *, manual: bool = False) -> str:
    """检查更新。返回状态：up_to_date / update_available / error。"""
    try:
        info = fetch_update_info()
    except ApiError as exc:
        if manual:
            from app.common.utils import show_dialog

            show_dialog(parent, f"检查更新失败：{exc}")
        return "error"
    except Exception:
        if manual:
            from app.common.utils import show_dialog

            show_dialog(parent, "检查更新失败，请稍后重试。")
        return "error"

    if info is None:
        if manual:
            from app.common.utils import show_dialog

            show_dialog(parent, f"当前已是最新版本（{VERSION}）。")
        return "up_to_date"

    if manual or should_prompt_update(info):
        show_update_dialog(parent, info)
        return "update_available"
    return "up_to_date"


def prompt_update_on_startup(parent: QWidget | None = None) -> None:
    check_and_prompt_update(parent, manual=False)
