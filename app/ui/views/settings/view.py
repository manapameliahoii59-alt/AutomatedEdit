# coding:utf-8
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QWidget, QLabel
from qfluentwidgets import FluentIcon as FIcon, CustomColorSettingCard, setThemeColor, qconfig
from qfluentwidgets import (SettingCardGroup, SettingCard, SwitchSettingCard, OptionsSettingCard, PrimaryPushSettingCard, PushSettingCard, ScrollArea,
                            ExpandLayout, setTheme, Dialog)

from app.common.config import cfg, FEEDBACK_URL, VERSION, YEAR, AUTHOR, AUTHOR_EMAIL
from app.common.utils import (
    BodyLabel,
    Dialog,
    LineEdit,
    StyleSheet,
    changdu_account_summary,
    open_changdu_account_dialog,
    setup_confirm_dialog,
    show_toast,
)
from app.data.services.update_service import check_and_prompt_update
from app.ui.components.icon import MyIcon


from app.ui.views.settings.view_model import SettingsViewModel

class SettingInterface(ScrollArea):
    logout = Signal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.vm = SettingsViewModel(self)
        self._parent = parent
        self._current_invite_code = ""
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

        # 每日使用配额
        self.quotaGroup = SettingCardGroup("每日使用配额", self.scrollWidget)
        self.clip_quota_card = PushSettingCard(
            '刷新配额',
            FIcon.VIDEO,
            '每日剪辑上限',
            '正在获取每日剪辑配额…',
            self.quotaGroup,
        )
        self.plan_quota_card = SettingCard(
            FIcon.DOCUMENT,
            '每日策划上限',
            '正在获取每日策划配额…',
            self.quotaGroup,
        )
        self.download_quota_card = SettingCard(
            FIcon.DOWNLOAD,
            '每日下载上限',
            '正在获取每日下载配额…',
            self.quotaGroup,
        )
        self.download_quota_card.hide()

        # 邀请
        self.inviteGroup = SettingCardGroup("邀请好友", self.scrollWidget)
        self.my_invite_card = PrimaryPushSettingCard(
            '复制邀请码',
            FIcon.SHARE,
            '我的专属邀请码',
            '正在获取专属邀请码…',
            self.inviteGroup,
        )
        self.bind_invite_card = PushSettingCard(
            '立即兑换',
            FIcon.ADD,
            '兑换好友邀请码',
            '输入好友邀请码，双方均可提升每日剪辑上限',
            self.inviteGroup,
        )
        btn_copy = getattr(self.my_invite_card, "button", None)
        if btn_copy is not None:
            btn_copy.setEnabled(False)

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
            '检查更新',
            FIcon.SYNC,
            '检查更新',
            f'当前版本 {VERSION}，有新版本时可直接下载安装',
            self.aboutGroup,
        )

        self.__init_widget()
        StyleSheet.SETTINGS.apply(self)
        self.vm.load_invite_info()
        self.vm.load_quota_info()

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
        self.quotaGroup.addSettingCard(self.clip_quota_card)
        self.quotaGroup.addSettingCard(self.plan_quota_card)
        self.quotaGroup.addSettingCard(self.download_quota_card)
        self.inviteGroup.addSettingCard(self.my_invite_card)
        self.inviteGroup.addSettingCard(self.bind_invite_card)
        self.changduGroup.addSettingCard(self.changdu_account_card)
        self.aboutGroup.addSettingCard(self.themeCard)
        self.aboutGroup.addSettingCard(self.themeColorCard)
        self.aboutGroup.addSettingCard(self.checkUpdateCard)
        self.aboutGroup.addSettingCard(self.aboutCard)
        self.expandLayout.setSpacing(28)
        self.expandLayout.setContentsMargins(60, 0, 60, 0)
        self.expandLayout.addWidget(self.personalGroup)
        self.expandLayout.addWidget(self.quotaGroup)
        self.expandLayout.addWidget(self.inviteGroup)
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
        self.clip_quota_card.clicked.connect(self.__on_refresh_quota_clicked)
        self.my_invite_card.clicked.connect(self.__on_copy_invite_code)
        self.bind_invite_card.clicked.connect(self.__on_bind_invite_clicked)
        self.vm.quotaInfoLoaded.connect(self.__on_quota_info_loaded)
        self.vm.inviteInfoLoaded.connect(self.__on_invite_info_loaded)
        self.vm.inviteBindFinished.connect(self.__on_bind_finished)

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
        if getattr(self, "_checking_update", False):
            return

        def _set_busy(busy: bool) -> None:
            self._checking_update = busy
            btn = getattr(self.checkUpdateCard, "button", None)
            if btn is not None:
                btn.setEnabled(not busy)
            if busy:
                self.checkUpdateCard.setContent("正在检查更新…")
            else:
                self.checkUpdateCard.setContent(
                    f"当前版本 {VERSION}，有新版本时可直接下载安装"
                )

        check_and_prompt_update(
            self.window(),
            manual=True,
            on_busy=_set_busy,
        )

    def showEvent(self, event):
        super().showEvent(event)
        self.vm.load_invite_info()
        self.vm.load_quota_info()

    def __on_refresh_quota_clicked(self):
        self.clip_quota_card.setContent("正在刷新配额…")
        self.vm.load_quota_info()
        show_toast(self, "正在刷新每日配额信息…", title="刷新配额")

    def __on_quota_info_loaded(self, data: dict):
        if not data:
            return
        clip_count = data.get("clip_count", 0)
        clip_limit = data.get("clip_limit", 0)
        plan_count = data.get("plan_count", 0)
        plan_limit = data.get("plan_limit", 0)
        download_count = data.get("download_count", 0)
        download_limit = data.get("download_limit", 0)
        download_enabled = data.get("download_enabled", True)
        invite_bonus = data.get("invite_bonus", 0)
        bonus_valid_days = data.get("bonus_valid_days", 0)
        base_clip_limit = data.get("base_clip_limit", clip_limit)

        # 每日剪辑上限
        if clip_limit <= 0:
            clip_content = f"今日已剪辑 {clip_count} 部 / 不限上限（畅享使用）"
        else:
            rem = max(0, clip_limit - clip_count)
            clip_content = f"今日已剪辑 {clip_count} 部 / 每日上限 {clip_limit} 部（今日剩余 {rem} 部）"
            if invite_bonus > 0:
                days_str = f"剩余有效期 {bonus_valid_days} 天" if bonus_valid_days > 0 else "永久有效"
                clip_content += f"\n包含基础永久额度 {base_clip_limit} 部 + 邀请奖励临时额度 {invite_bonus} 部（{days_str}）"
        self.clip_quota_card.setContent(clip_content)

        # 每日策划上限
        if plan_limit <= 0:
            plan_content = f"今日已策划 {plan_count} 部 / 不限上限"
        else:
            rem = max(0, plan_limit - plan_count)
            plan_content = f"今日已策划 {plan_count} 部 / 每日上限 {plan_limit} 部（今日剩余 {rem} 部）"
        self.plan_quota_card.setContent(plan_content)

        # 每日下载上限
        if download_enabled and download_limit > 0:
            self.download_quota_card.show()
            rem = max(0, download_limit - download_count)
            self.download_quota_card.setContent(
                f"今日已下载 {download_count} 部 / 每日上限 {download_limit} 部（今日剩余 {rem} 部）"
            )
        else:
            self.download_quota_card.hide()

    def __on_invite_info_loaded(self, data: dict):
        if not data:
            return
        is_enabled = data.get("is_enabled", True)
        if not is_enabled:
            self.inviteGroup.hide()
            return
        self.inviteGroup.show()
        self._current_invite_code = data.get("invite_code", "")
        has_used = data.get("has_used_invite", False)
        invited_by = data.get("invited_by", "")
        invitee_count = data.get("invitee_count", 0)
        reward = data.get("current_reward_per_invite", 5)
        valid_days = data.get("reward_valid_days", 30)
        valid_desc = f"（有效期 {valid_days} 天）" if valid_days and valid_days > 0 else "（永久有效）"

        if self._current_invite_code:
            self.my_invite_card.setTitle(f"我的专属邀请码：{self._current_invite_code}")
            self.my_invite_card.setContent(
                f"邀请好友注册使用，双方每日剪辑上限各 +{reward} 首{valid_desc} | 已成功邀请 {invitee_count} 人"
            )
            btn = getattr(self.my_invite_card, "button", None)
            if btn is not None:
                btn.setEnabled(True)

        btn_bind = getattr(self.bind_invite_card, "button", None)
        if has_used:
            self.bind_invite_card.setContent(
                f"已绑定邀请人：{invited_by or '好友'}（每日剪辑上限已成功提升）"
            )
            if btn_bind is not None:
                btn_bind.setText("已兑换")
                btn_bind.setEnabled(False)
        else:
            self.bind_invite_card.setContent(
                f"输入好友的邀请码，双方均可立即增加每日剪辑上限 +{reward} 首{valid_desc}（每人仅限一次）"
            )
            if btn_bind is not None:
                btn_bind.setText("立即兑换")
                btn_bind.setEnabled(True)

    def __on_copy_invite_code(self):
        code = getattr(self, "_current_invite_code", "")
        if not code:
            show_toast(self, "正在获取专属邀请码，请稍候…", level="warning")
            return
        from PySide6.QtGui import QGuiApplication

        clipboard = QGuiApplication.clipboard()
        if clipboard:
            clipboard.setText(code)
        show_toast(
            self,
            f"邀请码 {code} 已复制到剪贴板",
            title="复制成功",
            level="success",
        )

    def __on_bind_invite_clicked(self):
        dialog = Dialog("兑换好友邀请码", "", self.window())
        dialog.titleLabel.hide()
        dialog.contentLabel.hide()
        setup_confirm_dialog(dialog, window_title="兑换邀请码", yes_text="立即兑换")

        code_input = LineEdit(dialog)
        code_input.setPlaceholderText("请输入 6 位好友邀请码")
        code_input.setClearButtonEnabled(True)

        dialog.textLayout.setContentsMargins(24, 16, 24, 8)
        dialog.textLayout.addWidget(BodyLabel("输入好友分享给您的邀请码：", dialog))
        dialog.textLayout.addWidget(code_input)

        dialog.setFixedSize(400, 180)
        if not dialog.exec():
            return

        code = code_input.text().strip().upper()
        if not code:
            show_toast(self, "请输入有效的邀请码", level="warning")
            return

        btn = getattr(self.bind_invite_card, "button", None)
        if btn is not None:
            btn.setEnabled(False)
        self.bind_invite_card.setContent("正在提交兑换，请稍候…")
        self.vm.bind_invite_code(code)

    def __on_bind_finished(self, success: bool, msg: str, _res: dict):
        btn = getattr(self.bind_invite_card, "button", None)
        if btn is not None:
            btn.setEnabled(True)
        if success:
            show_toast(
                self,
                msg or "兑换成功！双方每日剪辑上限已成功提升",
                title="兑换成功",
                level="success",
            )
        else:
            show_toast(
                self,
                msg or "兑换失败，请检查邀请码是否正确",
                title="兑换失败",
                level="error",
            )
        self.vm.load_invite_info()

