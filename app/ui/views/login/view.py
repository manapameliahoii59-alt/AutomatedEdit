import sys
from qfluentwidgets import StateToolTip
from qframelesswindow import FramelessDialog
from PySide6.QtCore import Qt

from app.common.config import cfg, YEAR, AUTHOR
from app.common.utils import set_window_center, StyleSheet, show_dialog
from app.common.aes import aes_decrypt
from app.ui.generated.ui_login_window import Ui_Dialog
from app.core.container import Container

class LoginWindow(FramelessDialog):
    def __init__(self):
        super().__init__()
        self.vm = Container.login_view_model(self)
        self.ui = Ui_Dialog()
        self.ui.setupUi(self)
        
        # Init UI
        self.setFixedSize(self.width(), self.height())
        set_window_center(self)
        self.titleBar.raise_()
        self.ui.copyright.setText('© Copyright' + f" {YEAR}, {AUTHOR}")
        StyleSheet.LOGIN.apply(self)
        
        if sys.platform == "darwin":
            self.setSystemTitleBarButtonVisible(True)
            self.titleBar.closeBtn.hide()
            
        self._hide_legacy_captcha_ui()
        self.init_data()
        self.bind_events()
        self.bind_view_model()

    def _hide_legacy_captcha_ui(self):
        for widget in (self.ui.graphic, self.ui.image, self.ui.code, self.ui.getCode):
            widget.hide()

    def init_data(self):
        self.ui.username.setText(cfg.user.value)
        p = aes_decrypt(cfg.password.value)
        if p != '':
            self.ui.password.setText(p)
            self.ui.remember.setChecked(True)
            self.ui.session.setChecked(cfg.auto_login.value)

    def bind_events(self):
        self.ui.session.clicked.connect(lambda: self._link_checkbox(False))
        self.ui.remember.clicked.connect(lambda: self._link_checkbox(True))
        self.ui.login.clicked.connect(self._on_login_clicked)

    def bind_view_model(self):
        self.vm.loadingChanged.connect(self.loading)
        self.vm.loginSuccess.connect(self.accept)
        self.vm.loginFailed.connect(lambda msg: show_dialog(self, msg, '提示'))

    def _on_login_clicked(self):
        self.vm.login(
            self.ui.username.text(),
            self.ui.password.text(),
            self.ui.remember.isChecked(),
            self.ui.session.isChecked(),
        )

    def _link_checkbox(self, remember_click):
        if (not remember_click) and self.ui.session.isChecked():
            self.ui.remember.setChecked(True)
        if remember_click and (not self.ui.remember.isChecked()):
            self.ui.session.setChecked(False)

    def loading(self, is_loading):
        if is_loading:
            if not getattr(self, 'stateTooltip', None):
                self.stateTooltip = StateToolTip('加载中', '请耐心等待', self)
                self.stateTooltip.show()
                self.__move_tooltip()
        else:
            if getattr(self, 'stateTooltip', None):
                self.stateTooltip.setTitle('操作完成')
                self.stateTooltip.setContent('')
                self.stateTooltip.setState(isDone=True)
                self.stateTooltip = None

    def __move_tooltip(self):
        if getattr(self, 'stateTooltip', None):
            tl_x, tl_y, width, height = self.window().frameGeometry().getRect()
            width2 = self.stateTooltip.width()
            self.stateTooltip.move(width - width2 - 30, 30)
