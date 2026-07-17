# coding:utf-8
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QLabel
from qfluentwidgets import FluentIcon as FIcon, CustomColorSettingCard, setThemeColor, qconfig
from qfluentwidgets import (SettingCardGroup, SwitchSettingCard, OptionsSettingCard, PrimaryPushSettingCard, PushSettingCard, ScrollArea,
                            ExpandLayout, setTheme, Dialog)

from app.common.config import cfg, FEEDBACK_URL, VERSION, YEAR, AUTHOR, AUTHOR_EMAIL
from app.common.utils import StyleSheet, changdu_account_summary, open_changdu_account_dialog
from app.data.services.update_service import check_and_prompt_update
from app.ui.components.icon import MyIcon


from app.ui.views.settings.view_model import SettingsViewModel

class SettingInterface(ScrollArea):
    logout = Signal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.vm = SettingsViewModel(self)
        self._parent = parent
        self.setObjectName("setting_interface")
        self.scrollWidget = QWidget()
        self.scrollWidget.setObjectName("scrollWidget")

        self.expandLayout = ExpandLayout(self.scrollWidget)
        # setting label
        self.settingLabel = QLabel("设置", self)
        self.settingLabel.setObjectName('settingLabel')

        # personalization
        self.personalGroup = SettingCardGroup("账号设置", self.scrollWidget)
        self.save_password = SwitchSettingCard(
            MyIcon.SAVE,
            '保存密码', '是否需要加密保存你的密码',
            configItem=cfg.save_password,
            parent=self.personalGroup
        )
        self.auto_login = SwitchSettingCard(
            MyIcon.SAVE_SESSION,
            "自动登录", "下次打开软件是否自动登录",
            configItem=cfg.auto_login,
            parent=self.personalGroup
        )
        self.logoutCard = PrimaryPushSettingCard(
            '退出',
            FIcon.EMBED,
            '退出登录', '退出当前登录的账号，下次你必须重新登录',
            self.personalGroup
        )

        self.changduGroup = SettingCardGroup('常读平台', self.scrollWidget)
        self.changdu_account_card = PushSettingCard(
            '修改', FIcon.PEOPLE,
            '常读登录账号',
            changdu_account_summary(),
            self.changduGroup,
        )

        # application
        self.aboutGroup = SettingCardGroup('关于', self.scrollWidget)
        self.themeCard = OptionsSettingCard(
            cfg.themeMode,
            FIcon.BRUSH,
            "应用主题", "调整你的应用外观",
            texts=[
                self.tr('Light'), self.tr('Dark'),
                self.tr('Use system setting')
            ],
            parent=self.aboutGroup
        )
        self.themeColorCard = CustomColorSettingCard(
            cfg.themeColor,
            FIcon.PALETTE,
            '主题色',
            '调整你的应用主题颜色',
            self.aboutGroup
        )
        self.aboutCard = PrimaryPushSettingCard(
            '联系作者',
            FIcon.INFO,
            '当前版本:' + VERSION,
            f'作者：{AUTHOR}  邮箱：{AUTHOR_EMAIL}\n© Copyright {YEAR}, {AUTHOR}',
            self.aboutGroup
        )
        self.checkUpdateCard = PushSettingCard(
            '检查',
            FIcon.SYNC,
            '检查更新',
            f'当前版本 {VERSION}',
            self.aboutGroup,
        )

        self.__init_widget()
        StyleSheet.SETTINGS.apply(self)

    def __init_widget(self):
        self.resize(500, 400)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 70, 0, 50)
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)

        # initialize layout
        self.__init_layout()
        self.__connect_signal_to_slot()

    def __init_layout(self):
        self.settingLabel.move(20, 20)
        self.personalGroup.addSettingCard(self.save_password)
        self.personalGroup.addSettingCard(self.auto_login)
        self.personalGroup.addSettingCard(self.logoutCard)
        self.changduGroup.addSettingCard(self.changdu_account_card)
        self.aboutGroup.addSettingCard(self.themeCard)
        self.aboutGroup.addSettingCard(self.themeColorCard)
        self.aboutGroup.addSettingCard(self.checkUpdateCard)
        self.aboutGroup.addSettingCard(self.aboutCard)
        self.expandLayout.setSpacing(28)
        self.expandLayout.setContentsMargins(60, 0, 60, 0)
        self.expandLayout.addWidget(self.personalGroup)
        self.expandLayout.addWidget(self.changduGroup)
        self.expandLayout.addWidget(self.aboutGroup)

    def __connect_signal_to_slot(self):
        self.themeCard.optionChanged.connect(lambda ci: setTheme(cfg.themeMode.value))
        self.themeColorCard.colorChanged.connect(setThemeColor)
        self.aboutCard.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(FEEDBACK_URL)))
        self.checkUpdateCard.clicked.connect(self.__on_check_update)
        self.logoutCard.clicked.connect(self.__on_logout_clicked)
        self.save_password.checkedChanged.connect(self.__on_save_password_changed)
        self.changdu_account_card.clicked.connect(self.__on_set_changdu_account)

    def __on_save_password_changed(self, is_checked: bool):
        if not is_checked:
            qconfig.set(cfg.password, '')

    def __on_logout_clicked(self):
        w = Dialog(
            '退出登录',
            '确定要退出登录吗？',
            self.window()
        )
        w.yesButton.setText('确定')
        w.cancelButton.setText('取消')
        
        if w.exec():
            self.logout.emit()

    def __on_set_changdu_account(self):
        ok, email, password = open_changdu_account_dialog(self)
        if ok:
            self.changdu_account_card.setContent(changdu_account_summary())

    def __on_check_update(self):
        check_and_prompt_update(self.window(), manual=True)
