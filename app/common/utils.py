from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel, QLineEdit
from qfluentwidgets import BodyLabel, InfoBar, InfoBarPosition, LineEdit, Theme, Dialog, StyleSheetBase, qconfig

from app.common.aes import aes_encrypt
from app.common.config import cfg


class StyleSheet(StyleSheetBase, Enum):
    """ Style sheet  """

    WINDOW = "main_window"
    LOGIN = "login_window"
    SETTINGS = "setting_interface"

    def path(self, theme=Theme.AUTO):
        theme = qconfig.theme if theme == Theme.AUTO else theme
        return f":/resource/qss/{theme.value.lower()}/{self.value}.qss"


def setup_confirm_dialog(
    dialog: Dialog,
    *,
    window_title: str | None = None,
    yes_text: str = "确定",
    cancel_text: str = "取消",
    button_width: int = 88,
) -> None:
    """统一确认弹框：标题栏关闭按钮 + 右对齐等宽按钮。"""
    if window_title is not None:
        dialog.setWindowTitle(window_title)
    dialog.windowTitleLabel.hide()
    dialog.titleBar.show()
    dialog.titleBar.raise_()
    dialog.titleBar.minBtn.hide()
    dialog.titleBar.maxBtn.hide()
    dialog.yesButton.setText(yes_text)
    dialog.cancelButton.setText(cancel_text)
    dialog.yesButton.setFixedWidth(button_width)
    dialog.cancelButton.setFixedWidth(button_width)

    while dialog.buttonLayout.count():
        dialog.buttonLayout.takeAt(0)
    dialog.buttonLayout.setContentsMargins(24, 8, 24, 12)
    dialog.buttonLayout.addStretch(1)
    dialog.buttonLayout.addWidget(dialog.cancelButton, 0)
    dialog.buttonLayout.addWidget(dialog.yesButton, 0)
    dialog.buttonGroup.setFixedHeight(52)


def show_dialog(parent, content, title='提示', url=None, callback=None):
    w = Dialog(title, content, parent)
    w.contentLabel.setOpenExternalLinks(True)
    w.contentLabel.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if url:
        w.contentLabel.mousePressEvent = lambda e: QDesktopServices.openUrl(url)
    max_height = 400
    if parent:
        max_height = parent.screen().availableGeometry().height() * 0.5
    w.contentLabel.setMaximumHeight(max_height * 0.5)
    # w.contentLabel.setMinimumWidth(240)
    w.windowTitleLabel.hide()
    if not callback:
        w.yesButton.hide()
        w.cancelButton.setText('确定')
        w.buttonLayout.insertWidget(0, QLabel(''))
        w.buttonLayout.setStretch(0, 1)
        w.buttonLayout.setStretch(1, 1)
    if w.exec():
        if callback:
            callback()
    else:
        pass


def show_toast(
    parent,
    content: str,
    *,
    title: str = "提示",
    level: str = "success",
    duration: int = 3000,
) -> None:
    """非阻塞弱提示，类似 ElMessage，不阻断后续流程。"""
    toast_parent = parent.window() if parent and hasattr(parent, "window") else parent
    kwargs = dict(
        title=title,
        content=content,
        orient=Qt.Orientation.Horizontal,
        isClosable=True,
        position=InfoBarPosition.TOP,
        duration=duration,
        parent=toast_parent,
    )
    if level == "error":
        InfoBar.error(**kwargs)
    elif level == "warning":
        InfoBar.warning(**kwargs)
    elif level == "info":
        InfoBar.info(**kwargs)
    else:
        InfoBar.success(**kwargs)


def changdu_account_summary() -> str:
    email = cfg.changdu_email.value.strip()
    if not email:
        return "未设置"
    if cfg.changdu_password.value:
        return f"{email}（密码已配置）"
    return email


def open_changdu_account_dialog(parent) -> tuple[bool, str, str]:
    """打开常读登录账号设置对话框，返回 (是否保存, 邮箱, 密码明文)。"""
    dialog_parent = parent.window() if parent and hasattr(parent, "window") else parent
    dialog = Dialog("常读登录账号", "", dialog_parent)
    dialog.titleLabel.hide()
    dialog.contentLabel.hide()
    setup_confirm_dialog(dialog, window_title="常读登录账号", yes_text="保存")

    email_input = LineEdit(dialog)
    email_input.setPlaceholderText("请输入邮箱")
    email_input.setText(cfg.changdu_email.value)
    email_input.setClearButtonEnabled(True)

    password_input = LineEdit(dialog)
    password_input.setEchoMode(QLineEdit.EchoMode.Password)
    password_input.setPlaceholderText(
        "请输入密码" if not cfg.changdu_password.value else "留空则不修改密码"
    )
    password_input.setClearButtonEnabled(True)

    dialog.textLayout.setContentsMargins(24, 16, 24, 8)
    dialog.textLayout.addWidget(BodyLabel("邮箱", dialog))
    dialog.textLayout.addWidget(email_input)
    dialog.textLayout.addWidget(BodyLabel("密码", dialog))
    dialog.textLayout.addWidget(password_input)

    dialog.setFixedSize(420, 248)
    if not dialog.exec():
        return (False, "", "")

    email = email_input.text().strip()
    password = password_input.text().strip()
    qconfig.set(cfg.changdu_email, email)
    if password:
        qconfig.set(cfg.changdu_password, aes_encrypt(password))
    elif not email:
        qconfig.set(cfg.changdu_password, "")
    return (True, email, password)


def set_window_center(window):
    """ set window center """
    qr = window.frameGeometry()
    cp = window.screen().availableGeometry().center()
    qr.moveCenter(cp)
    window.move(qr.topLeft())
