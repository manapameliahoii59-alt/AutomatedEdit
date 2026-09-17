from PySide6.QtCore import Signal, QUrl
from PySide6.QtGui import QDesktopServices
from app.core.view_model import ViewModel
from app.common.config import cfg, FEEDBACK_URL
from qfluentwidgets import setTheme, setThemeColor

class SettingsViewModel(ViewModel):
    logoutRequested = Signal()
    themeChanged = Signal(str)
    themeColorChanged = Signal(str)
    inviteInfoLoaded = Signal(dict)
    inviteBindFinished = Signal(bool, str, dict)

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

    def load_invite_info(self):
        def _worker():
            try:
                from app.data.api.api import get_api
                data = get_api().fetch_invite_info()
                self.inviteInfoLoaded.emit(data or {})
            except Exception:
                pass
        import threading
        threading.Thread(target=_worker, daemon=True).start()

    def bind_invite_code(self, code: str):
        def _worker():
            try:
                from app.data.api.api import get_api
                from app.data.services.quota_service import QuotaService
                res = get_api().bind_invite_code(code)
                try:
                    QuotaService.instance().refresh()
                except Exception:
                    pass
                msg = res.get("message") or f"兑换成功！双方每日剪辑上限已各增加 +{res.get('reward', 5)} 首"
                self.inviteBindFinished.emit(True, msg, res)
            except Exception as e:
                msg = getattr(e, "message", str(e))
                self.inviteBindFinished.emit(False, msg, {})
        import threading
        threading.Thread(target=_worker, daemon=True).start()
