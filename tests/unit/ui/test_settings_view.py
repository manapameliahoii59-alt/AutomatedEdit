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
        assert settings_view.aboutGroup is not None

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
