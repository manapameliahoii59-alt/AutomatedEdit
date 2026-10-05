import pytest
from unittest.mock import MagicMock
from app.ui.views.settings.view import SettingInterface
from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt

class TestSettingInterface:
    @pytest.fixture
    def settings_view(self, qapp, mocker):
        # Patch StyleSheet apply to avoid loading resources
        mocker.patch('app.common.utils.StyleSheet.SETTINGS.apply')
        return SettingInterface(None)

    def test_init(self, settings_view):
        """Test initialization"""
        assert settings_view.scrollWidget is not None
        assert settings_view.personalGroup is not None
        assert settings_view.inviteGroup is not None
        assert settings_view.my_invite_card is not None
        assert settings_view.invite_code_label is not None
        assert settings_view.invite_code_label.isHidden()
        assert settings_view.bind_invite_card is not None
        assert settings_view.aboutGroup is not None

    def test_invite_info_loaded_enhancement(self, settings_view):
        """Test invite info loaded renders code inline without validity text"""
        data = {
            "is_enabled": True,
            "invite_code": "VIP888",
            "has_used_invite": False,
            "invitee_count": 3,
            "current_reward_per_invite": 5,
            "reward_valid_days": 30,
        }
        settings_view._SettingInterface__on_invite_info_loaded(data)
        assert settings_view.invite_code_label.text() == "VIP888"
        assert not settings_view.invite_code_label.isHidden()
        assert settings_view.my_invite_card.titleLabel.text() == "邀请码"
        my_content = settings_view.my_invite_card.contentLabel.text()
        assert "VIP888" not in my_content
        assert "有效期" not in my_content
        bind_content = settings_view.bind_invite_card.contentLabel.text()
        assert "有效期" not in bind_content

    def test_quota_info_loaded_enhancement(self, settings_view):
        """Test quota info loaded does not show validity days or temporary quota text"""
        data = {
            "clip_count": 2,
            "clip_limit": 15,
            "invite_bonus": 5,
            "bonus_valid_days": 30,
            "base_clip_limit": 10,
        }
        settings_view._SettingInterface__on_quota_info_loaded(data)
        quota_content = settings_view.clip_quota_card.contentLabel.text()
        assert "有效期" not in quota_content
        assert "临时" not in quota_content
        assert "基础额度 10 部" in quota_content
        assert "邀请奖励额度 5 部" in quota_content

    def test_logout_signal(self, settings_view, qtbot, mocker):
        """Test logout button triggers signal"""
        # Mock Dialog in the module
        mock_dialog_cls = mocker.patch('app.ui.views.settings.view.Dialog')
        mock_instance = mock_dialog_cls.return_value
        mock_instance.exec.return_value = True
        
        # We need to ensure the slot is called.
        # logoutCard.clicked.connect(self.__on_logout_clicked)
        # So we emit clicked.
        
        with qtbot.waitSignal(settings_view.logout) as blocker:
            settings_view.logoutCard.clicked.emit()
            
        assert blocker.signal_triggered
