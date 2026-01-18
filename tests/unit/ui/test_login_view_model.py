import pytest
from unittest.mock import MagicMock
from app.ui.views.login.view_model import LoginViewModel
from app.common.config import cfg
from qfluentwidgets import qconfig

class TestLoginViewModel:
    @pytest.fixture
    def mock_auth_service(self):
        return MagicMock()

    @pytest.fixture
    def mock_task_manager(self, mocker):
        return mocker.patch('app.ui.views.login.view_model.task_manager')

    @pytest.fixture
    def view_model(self, mock_auth_service, qapp):
        vm = LoginViewModel()
        vm.auth_service = mock_auth_service
        return vm

    def test_login_validation_failure(self, view_model, qtbot):
        """Test login fails with missing fields"""
        with qtbot.waitSignal(view_model.loginFailed) as blocker:
            view_model.login("", "password", "captcha", "code", False, False)
        
        assert "请认真填写登录信息" in blocker.args[0]

    def test_login_success(self, view_model, mock_task_manager, mock_auth_service, qtbot, mocker):
        """Test login success flow"""
        # Mock task_manager.submit_task to call success callback immediately
        def side_effect(func, args, on_success, on_error):
            on_success(True)
        
        mock_task_manager.submit_task.side_effect = side_effect
        
        # Mock qconfig.set
        mock_set = mocker.patch.object(qconfig, 'set')
        
        with qtbot.waitSignal(view_model.loginSuccess):
            view_model.login("user", "pass", "captcha", "code", True, True)
            
        # Verify AuthService called via task manager
        mock_task_manager.submit_task.assert_called()
        args, _ = mock_task_manager.submit_task.call_args
        assert args[0] == mock_auth_service.login
        
        # Verify config saved
        assert mock_set.call_count >= 1

    def test_login_error(self, view_model, mock_task_manager, qtbot):
        """Test login error flow"""
        def side_effect(func, args, on_success, on_error):
            on_error("Network Error")
            
        mock_task_manager.submit_task.side_effect = side_effect
        
        with qtbot.waitSignal(view_model.loginFailed) as blocker:
            view_model.login("user", "pass", "captcha", "code", False, False)
            
        assert "Network Error" in blocker.args[0]

    def test_get_captcha(self, view_model, mock_task_manager, mock_auth_service, qtbot):
        """Test get_captcha flow"""
        data = {'data': 'img'}
        def side_effect(func, on_success, on_error):
            on_success(data)
            
        mock_task_manager.submit_task.side_effect = side_effect
        
        with qtbot.waitSignal(view_model.captchaReceived) as blocker:
            view_model.get_captcha()
            
        assert blocker.args[0] == data
