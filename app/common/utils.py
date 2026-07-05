from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QLabel
from qfluentwidgets import Theme, Dialog, StyleSheetBase, qconfig


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


def set_window_center(window):
    """ set window center """
    qr = window.frameGeometry()
    cp = window.screen().availableGeometry().center()
    qr.moveCenter(cp)
    window.move(qr.topLeft())
