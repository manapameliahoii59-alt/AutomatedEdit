from PySide6.QtCore import Signal
from app.core.view_model import ViewModel
from app.data.services.auth_service import AuthService
from app.core.task_manager import task_manager
from app.common.config import cfg
from app.common.aes import aes_encrypt
from qfluentwidgets import qconfig

class LoginViewModel(ViewModel):
    loginSuccess = Signal()
    loginFailed = Signal(str)
    loadingChanged = Signal(bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.auth_service = None # Injected via DI

    def login(self, username, password, remember_me, auto_login):
        if not username or not password:
             self.loginFailed.emit('请输入用户名和密码')
             return

        self.loadingChanged.emit(True)
        
        def on_success(_result):
            self._handle_login_success(username, password, remember_me, auto_login)
            
        task_manager.submit_task(
            self.auth_service.login,
            args=(username, password),
            on_success=on_success,
            on_error=self._handle_error
        )

    def _handle_login_success(self, username, password, remember_me, auto_login):
        qconfig.set(cfg.user, aes_encrypt(username))
        if remember_me:
            qconfig.set(cfg.password, aes_encrypt(password))
            qconfig.set(cfg.save_password, True)
        else:
            qconfig.set(cfg.password, '')
            qconfig.set(cfg.save_password, False)
        
        qconfig.set(cfg.auto_login, auto_login)
        
        self.loadingChanged.emit(False)
        self.loginSuccess.emit()

    def _handle_error(self, error):
        self.loadingChanged.emit(False)
        self.loginFailed.emit(str(error))
