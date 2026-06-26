import pytest
from unittest.mock import MagicMock
from app.ui.views.login.view_model import LoginViewModel
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
        with qtbot.waitSignal(view_model.loginFailed) as blocker:
            view_model.login("", "password", False, False)
        
        assert "用户名和密码" in blocker.args[0]

    def test_login_success(self, view_model, mock_task_manager, mock_auth_service, qtbot, mocker):
        def side_effect(func, args, on_success, on_error):
            on_success(True)
        
        mock_task_manager.submit_task.side_effect = side_effect
        mocker.patch.object(qconfig, 'set')
        
        with qtbot.waitSignal(view_model.loginSuccess):
            view_model.login("user", "pass", True, True)
            
        mock_task_manager.submit_task.assert_called()
        args, _ = mock_task_manager.submit_task.call_args
        assert args[0] == mock_auth_service.login

    def test_login_error(self, view_model, mock_task_manager, qtbot):
        def side_effect(func, args, on_success, on_error):
            on_error("Network Error")
            
        mock_task_manager.submit_task.side_effect = side_effect
        
        with qtbot.waitSignal(view_model.loginFailed) as blocker:
            view_model.login("user", "pass", False, False)
            
        assert "Network Error" in blocker.args[0]
