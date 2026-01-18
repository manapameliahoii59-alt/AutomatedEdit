import pytest
from unittest.mock import MagicMock
from PySide6.QtCore import Qt
from app.ui.views.login.view import LoginWindow
from app.core.container import Container
from app.ui.views.login.view_model import LoginViewModel

class TestLoginView:
    @pytest.fixture
    def mock_vm(self, mocker):
        vm = MagicMock(spec=LoginViewModel)
        # Setup signals
        vm.loadingChanged = MagicMock()
        vm.loadingChanged.connect = MagicMock()
        vm.loginSuccess = MagicMock()
        vm.loginSuccess.connect = MagicMock()
        vm.loginFailed = MagicMock()
        vm.loginFailed.connect = MagicMock()
        vm.captchaReceived = MagicMock()
        vm.captchaReceived.connect = MagicMock()
        return vm

    @pytest.fixture
    def login_window(self, mock_vm, mocker, qapp):
        # Patch Container to return mock VM
        mocker.patch('app.core.container.Container.login_view_model', return_value=mock_vm)
        
        # Patch StyleSheet to avoid reading QRC resources if not compiled or issue with path
        # But we added paths in conftest so it might be fine. 
        # If it fails, we mock apply.
        mocker.patch('app.common.utils.StyleSheet.LOGIN.apply')
        
        window = LoginWindow()
        return window

    def test_init(self, login_window):
        """Test window initialization"""
        assert login_window.ui.username is not None
        assert login_window.ui.password is not None

    def test_checkbox_logic(self, login_window, qtbot):
        """Test checkbox linking logic"""
        # If session is checked, remember must be checked
        login_window.ui.session.setChecked(True)
        # Trigger clicked
        # login_window.ui.session.clicked.emit(True) # Fails with TypeError
        # We can use qtbot to simulate click if we want to test the connection
        # But here we just want to verify logic.
        
        # Calling the handler directly is also an option if we want to test the method
        # login_window._link_checkbox(False)
        
        # But better to simulate user interaction
        qtbot.mouseClick(login_window.ui.session, Qt.LeftButton)
        
        # Manually call because signal connection might be complex to trace in test if not shown
        # But we trust the code: self.ui.session.clicked.connect(lambda: self._link_checkbox(False))
        # Wait, setChecked doesn't emit clicked. We must emit clicked or click with mouse.
        
        # Let's reset
        login_window.ui.remember.setChecked(False)
        login_window.ui.session.setChecked(False)
        
        # Click session
        qtbot.mouseClick(login_window.ui.session, Qt.LeftButton)
        assert login_window.ui.session.isChecked()
        assert login_window.ui.remember.isChecked()

        # Uncheck remember
        qtbot.mouseClick(login_window.ui.remember, Qt.LeftButton)
        assert not login_window.ui.remember.isChecked()
        assert not login_window.ui.session.isChecked()

    def test_login_click(self, login_window, mock_vm, qtbot):
        """Test login button triggers VM"""
        login_window.ui.username.setText("user")
        login_window.ui.password.setText("pass")
        login_window.ui.graphic.setText("cap")
        login_window.ui.code.setText("123")
        
        qtbot.mouseClick(login_window.ui.login, Qt.LeftButton)
        
        mock_vm.login.assert_called_with("user", "pass", "cap", "123", login_window.ui.remember.isChecked(), login_window.ui.session.isChecked())

    def test_captcha_click(self, login_window, mock_vm, qtbot):
        """Test captcha click triggers VM"""
        qtbot.mouseClick(login_window.ui.image, Qt.LeftButton)
        mock_vm.get_captcha.assert_called()
