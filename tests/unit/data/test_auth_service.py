import pytest
from unittest.mock import MagicMock
from app.data.services.auth_service import AuthService
from app.data.api.api import LoginResult


class TestAuthService:
    @pytest.fixture
    def mock_get_api(self, mocker):
        return mocker.patch('app.data.services.auth_service.get_api')

    def test_login_stores_token(self, mock_get_api, mocker):
        mock_api = MagicMock()
        mock_api.login.return_value = LoginResult(access_token='tok', username='u', role='user')
        mock_api.fetch_secrets.return_value = {'deepseek_keys': 'sk-1', 'dashscope_key': ''}
        mock_get_api.return_value = mock_api
        mock_set = mocker.patch('app.data.services.auth_service.qconfig.set')

        service = AuthService()
        result = service.login("user", "pass")

        assert result.access_token == 'tok'
        mock_api.login.assert_called_once_with("user", "pass")
        from app.common.config import cfg
        mock_set.assert_any_call(cfg.access_token, 'tok')

    def test_try_auto_login_without_token(self, mock_get_api, mocker):
        mocker.patch('app.data.services.auth_service.cfg')
        from app.data.services.auth_service import cfg
        cfg.access_token.value = ''

        service = AuthService()
        assert service.try_auto_login() is False

    def test_logout_clears_token(self, mocker):
        mock_set = mocker.patch('app.data.services.auth_service.qconfig.set')
        AuthService().logout()
        mock_set.assert_called()
