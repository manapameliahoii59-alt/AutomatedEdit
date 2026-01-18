from PySide6.QtCore import Signal, QUrl
from PySide6.QtGui import QDesktopServices
from app.core.view_model import ViewModel
from app.common.config import cfg, FEEDBACK_URL
from qfluentwidgets import setTheme, setThemeColor

class SettingsViewModel(ViewModel):
    logoutRequested = Signal()
    themeChanged = Signal(str)
    themeColorChanged = Signal(str)

    def logout(self):
        self.logoutRequested.emit()

    def set_theme(self, mode):
        setTheme(mode)
        self.themeChanged.emit(mode)

    def set_theme_color(self, color):
        setThemeColor(color)
        self.themeColorChanged.emit(color.name())

    def open_feedback(self):
        QDesktopServices.openUrl(QUrl(FEEDBACK_URL))
