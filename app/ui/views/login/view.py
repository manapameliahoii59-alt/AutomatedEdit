import sys
from qfluentwidgets import StateToolTip
from qframelesswindow import FramelessDialog
from PySide6.QtGui import QPixmap, QBitmap, QPainter, QColor
from PySide6.QtCore import Qt, QByteArray

from common.config import cfg, YEAR, AUTHOR
from common.utils import set_window_center, StyleSheet, show_dialog
from common.aes import aes_decrypt
from ui_view.ui_login_window import Ui_Dialog
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
            
        self.init_data()
        self.bind_events()
        self.bind_view_model()

    def init_data(self):
        self.ui.username.setText(cfg.user.value)
        p = aes_decrypt(cfg.password.value)
        if p != '':
            self.ui.password.setText(p)
            self.ui.remember.setChecked(True)
            self.ui.session.setChecked(cfg.auto_login.value)

    def bind_events(self):
        # Checkbox logic
        self.ui.session.clicked.connect(lambda: self._link_checkbox(False))
        self.ui.remember.clicked.connect(lambda: self._link_checkbox(True))
        
        # Login
        self.ui.login.clicked.connect(self._on_login_clicked)
        self.ui.image.clicked.connect(self.vm.get_captcha)
        self.ui.getCode.clicked.connect(lambda: show_dialog(self, "获取短信验证码操作", "测试"))

    def bind_view_model(self):
        self.vm.loadingChanged.connect(self.loading)
        self.vm.loginSuccess.connect(self.accept)
        self.vm.loginFailed.connect(lambda msg: show_dialog(self, msg, '提示'))
        self.vm.captchaReceived.connect(self._update_captcha)

    def _on_login_clicked(self):
        self.vm.login(
            self.ui.username.text(),
            self.ui.password.text(),
            self.ui.graphic.text(),
            self.ui.code.text(),
            self.ui.remember.isChecked(),
            self.ui.session.isChecked()
        )

    def _link_checkbox(self, remember_click):
        if (not remember_click) and self.ui.session.isChecked():
            self.ui.remember.setChecked(True)
        if remember_click and (not self.ui.remember.isChecked()):
            self.ui.session.setChecked(False)

    def _update_captcha(self, img_data):
        pixmap = QPixmap()
        pixmap.loadFromData(QByteArray.fromBase64(img_data['data'].encode()))
        pixmap = pixmap.scaled(self.ui.image.size())
        self.ui.image.setPixmap(pixmap)
        
        # Apply mask (rounded corners)
        size = self.ui.image.size()
        mask = QBitmap(size)
        painter = QPainter(mask)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(0, 0, size.width(), size.height(), Qt.GlobalColor.white)
        painter.setBrush(QColor(0, 0, 0))
        painter.drawRoundedRect(0, 0, size.width(), size.height(), 4, 4)
        painter.end()
        self.ui.image.setMask(mask)

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
