import sys
from PySide6.QtCore import QRect
from PySide6.QtGui import QIcon
from qfluentwidgets import FluentWindow, NavigationItemPosition, FluentIcon as FIF, qconfig

from app.common.config import cfg
from app.ui.components.icon import MyIcon
from app.core.navigation import LazyViewProxy
from app.ui.views.page_one.view import PageOne
from app.ui.views.page_two.view import PageTwo
from app.ui.views.batch_edit.view import BatchEditPage
from app.ui.views.settings.view import SettingInterface

class MainWindow(FluentWindow):
    """ 主界面 (Refactored) """

    def __init__(self):
        super().__init__()
        self.is_logout = False
        self.init_window()
        self.init_navigation()

    def init_window(self):
        if sys.platform != "darwin":
            self.setWindowIcon(QIcon(':/resource/images/logo.png'))
            self.setWindowTitle('MyApp')
        self.resize(900, 700)
        
        # Center window
        if self.screen():
            self.move((self.screen().size().width() - self.width()) / 2,
                      (self.screen().size().height() - self.height()) / 2)
            
        if sys.platform == "darwin":
            self.navigationInterface.panel.setReturnButtonVisible(False)
            self.navigationInterface.panel.topLayout.setContentsMargins(4, 24, 4, 0)
        else:
            self.navigationInterface.setExpandWidth(150)

    def init_navigation(self):
        # Use LazyViewProxy for lazy loading
        self.pageOne = LazyViewProxy(lambda: PageOne(self), "pageOne")
        self.pageTwo = LazyViewProxy(lambda: PageTwo(self), "pageTwo")
        self.batchEditPage = LazyViewProxy(lambda: BatchEditPage(self), "batchEditPage")
        # self.settingInterface = LazyViewProxy(lambda: SettingInterface(self), "settingInterface")
        self.settingInterface = SettingInterface(self)
        self.settingInterface.logout.connect(self.logout)

        self.addSubInterface(self.pageOne, MyIcon.CLICK, '页面一')
        self.addSubInterface(self.pageTwo, MyIcon.EXCEL, '页面二')
        self.addSubInterface(self.batchEditPage, MyIcon.TOOL, '批量打码')
        
        self.addSubInterface(self.settingInterface, FIF.SETTING, '设置', NavigationItemPosition.BOTTOM)

    def logout(self):
        qconfig.set(cfg.auto_login, False)
        self.is_logout = True
        self.close()

    def systemTitleBarRect(self, size):
        return QRect(0, 0, 75, size.height())
