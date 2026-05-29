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
        # We need to capture the object_name passed to constructor
        def side_effect(factory, object_name, parent=None):
            return MockWidget(object_name)
            
        mock_cls.side_effect = side_effect
        return mock_cls
    
    @pytest.fixture
    def mock_settings(self, mocker):
        mock_cls = mocker.patch('app.ui.views.main_window.view.SettingInterface')
        # SettingInterface is instantiated directly: SettingInterface(self)
        # It's a class.
        instance = MockWidget("settingInterface")
        instance.logout = MagicMock()
        mock_cls.return_value = instance
        return mock_cls

    def test_init(self, mock_lazy_proxy, mock_settings, qapp):
        """Test initialization"""
        window = MainWindow()
        assert window.pageOne is not None
        assert window.pageTwo is not None
        assert window.batchEditPage is not None
        assert window.settingInterface is not None

    def test_logout(self, mock_lazy_proxy, mock_settings, mocker, qapp):
        """Test logout functionality"""
        window = MainWindow()
        
        # Mock qconfig.set
        mock_set = mocker.patch.object(qconfig, 'set')
        # Mock close
        window.close = MagicMock()
        
        window.logout()
        
        assert window.is_logout is True
        window.close.assert_called_once()
