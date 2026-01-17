from PySide6.QtCore import Signal
from app.core.view_model import ViewModel
from app.data.services.auth_service import AuthService
from workers.TaskManager import task_manager
from common.config import cfg
from common.aes import aes_encrypt
from qfluentwidgets import qconfig

class LoginViewModel(ViewModel):
    loginSuccess = Signal()
    loginFailed = Signal(str)
    captchaReceived = Signal(dict)
    loadingChanged = Signal(bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.auth_service = None # Injected via DI

    def login(self, username, password, captcha, code, remember_me, auto_login):
        # Validation
        if not all([username, password, captcha, code]):
             self.loginFailed.emit('请认真填写登录信息！')
             return

        self.loadingChanged.emit(True)
        
        # Define success callback wrapper to handle config saving
        def on_success(result):
            self._handle_login_success(username, password, remember_me, auto_login)
            
        task_manager.submit_task(
            self.auth_service.login,
            args=(username, password, captcha, code),
            on_success=on_success,
            on_error=self._handle_error
        )

    def get_captcha(self):
        self.loadingChanged.emit(True)
        task_manager.submit_task(
            self.auth_service.get_captcha,
            on_success=self._handle_captcha,
            on_error=self._handle_error
        )

    def _handle_login_success(self, username, password, remember_me, auto_login):
        # Save config logic
        qconfig.set(cfg.user, username)
        if remember_me:
            qconfig.set(cfg.password, aes_encrypt(password))
            qconfig.set(cfg.save_password, True)
        else:
            qconfig.set(cfg.password, '')
            qconfig.set(cfg.save_password, False)
        
        qconfig.set(cfg.auto_login, auto_login)
        
        self.loadingChanged.emit(False)
        self.loginSuccess.emit()

    def _handle_captcha(self, data):
        self.loadingChanged.emit(False)
        self.captchaReceived.emit(data)

    def _handle_error(self, error):
        self.loadingChanged.emit(False)
        self.loginFailed.emit(str(error))
