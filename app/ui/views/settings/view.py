# coding:utf-8
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QLabel, QFileDialog, QInputDialog
from qfluentwidgets import FluentIcon as FIcon, CustomColorSettingCard, setThemeColor, InfoBarPosition, qconfig
from qfluentwidgets import (SettingCardGroup, SwitchSettingCard, OptionsSettingCard, PrimaryPushSettingCard, PushSettingCard, ScrollArea,
                            ExpandLayout, InfoBar, setTheme, Dialog)

from app.common.config import cfg, FEEDBACK_URL, VERSION, YEAR, AUTHOR
from app.common.ffmpeg_paths import effective_ffmpeg_display, effective_ffprobe_display
from app.common.utils import StyleSheet, show_dialog
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

        # clip tools
        self.clipGroup = SettingCardGroup('剪辑工具', self.scrollWidget)
        self.api_key_card = PushSettingCard(
            '修改', FIcon.CERTIFICATE,
            'DeepSeek API Key',
            '当前已设置' if cfg.deepseek_api_keys.value else '未设置',
            self.clipGroup
        )
        self.ffmpeg_card = PushSettingCard(
            '浏览', FIcon.VIDEO,
            'FFmpeg 路径',
            effective_ffmpeg_display(),
            self.clipGroup
        )
        self.ffprobe_card = PushSettingCard(
            '浏览', FIcon.VIDEO,
            'FFprobe 路径',
            effective_ffprobe_display(),
            self.clipGroup
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
            '© Copyright' + f" {YEAR}, {AUTHOR}",
            self.aboutGroup
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
        self.clipGroup.addSettingCard(self.api_key_card)
        self.clipGroup.addSettingCard(self.ffmpeg_card)
        self.clipGroup.addSettingCard(self.ffprobe_card)
        self.aboutGroup.addSettingCard(self.themeCard)
        self.aboutGroup.addSettingCard(self.themeColorCard)
        self.aboutGroup.addSettingCard(self.aboutCard)
        self.expandLayout.setSpacing(28)
        self.expandLayout.setContentsMargins(60, 0, 60, 0)
        self.expandLayout.addWidget(self.personalGroup)
        self.expandLayout.addWidget(self.clipGroup)
        self.expandLayout.addWidget(self.aboutGroup)

    def __connect_signal_to_slot(self):
        self.themeCard.optionChanged.connect(lambda ci: setTheme(cfg.themeMode.value))
        self.themeColorCard.colorChanged.connect(setThemeColor)
        self.aboutCard.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(FEEDBACK_URL)))
        self.logoutCard.clicked.connect(self.__on_logout_clicked)
        self.save_password.checkedChanged.connect(self.__on_save_password_changed)
        self.api_key_card.clicked.connect(self.__on_set_api_key)
        self.ffmpeg_card.clicked.connect(self.__on_set_ffmpeg)
        self.ffprobe_card.clicked.connect(self.__on_set_ffprobe)

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

    def __on_set_api_key(self):
        keys, ok = QInputDialog.getMultiLineText(self, 'DeepSeek API Key',
            '输入 DeepSeek API Key（多个用逗号分隔）：',
            cfg.deepseek_api_keys.value)
        if ok:
            qconfig.set(cfg.deepseek_api_keys, keys)
            self.api_key_card.setContent('已设置' if keys else '未设置')

    def __on_set_ffmpeg(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择 FFmpeg 可执行文件',
            cfg.ffmpeg_path.value or '', '可执行文件 (*.exe);;所有文件 (*.*)')
        if path:
            qconfig.set(cfg.ffmpeg_path, path)
            self.ffmpeg_card.setContent(path)

    def __on_set_ffprobe(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择 FFprobe 可执行文件',
            cfg.ffprobe_path.value or '', '可执行文件 (*.exe);;所有文件 (*.*)')
        if path:
            qconfig.set(cfg.ffprobe_path, path)
            self.ffprobe_card.setContent(path)
