import pytest
from unittest.mock import MagicMock
from PySide6.QtWidgets import QWidget
from app.ui.views.main_window.view import MainWindow
from app.common.config import cfg, qconfig

# Helper class for mocking widgets
class MockWidget(QWidget):
    def __init__(self, objectName=""):
        super().__init__()
        self.setObjectName(objectName)

class TestMainWindow:
    @pytest.fixture
    def mock_lazy_proxy(self, mocker):
        mock_cls = mocker.patch('app.ui.views.main_window.view.LazyViewProxy')
        def side_effect(factory, object_name, parent=None):
            return MockWidget(object_name)
        mock_cls.side_effect = side_effect
        return mock_cls
    
    @pytest.fixture
    def mock_settings(self, mocker):
        mock_cls = mocker.patch('app.ui.views.main_window.view.SettingInterface')
        instance = MockWidget("settingInterface")
        instance.logout = MagicMock()
        mock_cls.return_value = instance
        return mock_cls

    @pytest.fixture(autouse=True)
    def mock_access_control(self, mocker):
        mocker.patch.object(MainWindow, '_check_access')
        mocker.patch('app.ui.views.main_window.view.access_control.refresh')

    def test_init_with_default_tabs(self, mock_lazy_proxy, mock_settings, mocker, qapp):
        """Test default tabs: video_download, clip_edit, setting"""
        mock_add = mocker.patch.object(MainWindow, 'addSubInterface')
        mock_switch = mocker.patch.object(MainWindow, 'switchTo')
        qconfig.set(cfg.enabled_tabs, "video_download,clip_edit")
        window = MainWindow()
        assert window.clipEditPage is not None
        assert window.videoDownloadPage is not None
        assert window.batchEditPage is not None
        assert window.settingInterface is not None

        added_widgets = [call.args[0] for call in mock_add.call_args_list]
        assert window.videoDownloadPage in added_widgets
        assert window.clipEditPage in added_widgets
        assert window.batchEditPage not in added_widgets
        assert window.settingInterface in added_widgets
        mock_switch.assert_called_with(window.videoDownloadPage)

    def test_init_with_batch_edit_only(self, mock_lazy_proxy, mock_settings, mocker, qapp):
        """Test customized tabs: only batch_edit and setting"""
        mock_add = mocker.patch.object(MainWindow, 'addSubInterface')
        mock_switch = mocker.patch.object(MainWindow, 'switchTo')
        qconfig.set(cfg.enabled_tabs, "batch_edit")
        window = MainWindow()

        added_widgets = [call.args[0] for call in mock_add.call_args_list]
        assert window.videoDownloadPage not in added_widgets
        assert window.clipEditPage not in added_widgets
        assert window.batchEditPage in added_widgets
        assert window.settingInterface in added_widgets
        mock_switch.assert_called_with(window.batchEditPage)

    def test_handoff_guarded_when_clip_edit_disabled(self, mock_lazy_proxy, mock_settings, mocker, qapp):
        """When clip_edit is disabled, handoff_to_clip_edit does not attempt to load clipEditPage"""
        mocker.patch.object(MainWindow, 'addSubInterface')
        mocker.patch.object(MainWindow, 'switchTo')
        qconfig.set(cfg.enabled_tabs, "batch_edit")
        window = MainWindow()
        window.clipEditPage.ensure_loaded = MagicMock()
        window.handoff_to_clip_edit(["/path/to/drama"])
        window.clipEditPage.ensure_loaded.assert_not_called()

    def test_logout(self, mock_lazy_proxy, mock_settings, mocker, qapp):
        """Test logout functionality"""
        mocker.patch.object(MainWindow, 'addSubInterface')
        mocker.patch.object(MainWindow, 'switchTo')
        window = MainWindow()
        mock_set = mocker.patch.object(qconfig, 'set')
        window.close = MagicMock()
        window.logout()
        assert window.is_logout is True
        window.close.assert_called_once()
