from PySide6.QtGui import QIcon
from qfluentwidgets import FluentWindow, NavigationItemPosition

from components.icon import MyIcon
from qfluentwidgets import FluentIcon as FIF
from pages.page_one import PageOne
from pages.page_two import PageTwo
from view.setting_interface import SettingInterface


class MainWindow(FluentWindow):
    """ 主界面 """

    def __init__(self):
        super().__init__()

        # 创建子界面，实际使用时将 Widget 换成自己的子界面
        self.settingInterface = SettingInterface(self)
        self.pageOne = PageOne(self)
        self.pageTwo = PageTwo(self)
        self.init_navigation()
        self.init_window()

    def init_navigation(self):
        sub_interface_list = [
            {'widget': self.pageOne, 'icon': MyIcon.CLICK, 'text': 'Home'},
            {'widget': self.pageTwo, 'icon': MyIcon.EXCEL, 'text': 'Video library'}
        ]
        for item in sub_interface_list:
            self.addSubInterface(item['widget'], item['icon'], item['text'])

        self.addSubInterface(self.settingInterface, FIF.SETTING, 'Settings', NavigationItemPosition.BOTTOM)

    def init_window(self):
        self.resize(900, 700)
        # 访问qt资源
        self.setWindowIcon(QIcon(':/resource/images/logo.png'))
        self.setWindowTitle('MyApp')
