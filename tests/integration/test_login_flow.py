import pytest
from unittest.mock import MagicMock
from app.ui.views.login.view_model import LoginViewModel
from app.core.container import Container
from app.data.services.auth_service import AuthService

class TestLoginIntegration:
    @pytest.fixture
    def setup_services(self, mocker):
        # Reset container
        Container._services = {}
        
        # Mock API used by AuthService
        mock_api = mocker.patch('app.data.services.auth_service.demo_api')
        
        # Register real AuthService
        auth_service = AuthService()
        Container.register(AuthService, auth_service)
        
        return mock_api

    def test_login_flow_success(self, setup_services, qtbot):
        """
        Integration test: ViewModel -> AuthService -> Mock API
        """
        mock_api = setup_services
        mock_api.login.return_value = True
        
        # Create ViewModel (it injects AuthService internally or we set it)
        # LoginViewModel currently does: self.auth_service = None
        # And Container factory sets it.
        vm = Container.login_view_model()
        
        # We need to handle threading. TaskManager uses QThreadPool.
        # We can use qtbot to wait for signals.
        
        with qtbot.waitSignal(vm.loginSuccess, timeout=2000):
            vm.login("user", "pass", "cap", "123", True, True)
            
        # Verify API was called
        mock_api.login.assert_called_with("user", "pass", "cap", "123")
        
    def test_login_flow_failure(self, setup_services, qtbot):
        """
        Integration test: ViewModel -> AuthService -> Mock API (Error)
        """
        mock_api = setup_services
        mock_api.login.side_effect = Exception("Invalid Credentials")
        
        vm = Container.login_view_model()
        
        with qtbot.waitSignal(vm.loginFailed, timeout=2000) as blocker:
            vm.login("user", "pass", "cap", "123", False, False)
            
        assert "Invalid Credentials" in blocker.args[0]
