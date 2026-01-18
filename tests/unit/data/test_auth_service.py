import pytest
from unittest.mock import MagicMock
from app.data.services.auth_service import AuthService

class TestAuthService:
    @pytest.fixture
    def mock_api(self, mocker):
        return mocker.patch('app.data.services.auth_service.demo_api')

    def test_login(self, mock_api):
        """Test login delegation"""
        service = AuthService()
        mock_api.login.return_value = True
        
        result = service.login("user", "pass", "captcha", "123456")
        
        assert result is True
        mock_api.login.assert_called_once_with("user", "pass", "captcha", "123456")

    def test_get_captcha(self, mock_api):
        """Test captcha delegation"""
        service = AuthService()
        expected_data = {'data': 'base64image'}
        mock_api.get_captcha.return_value = expected_data
        
        result = service.get_captcha()
        
        assert result == expected_data
        mock_api.get_captcha.assert_called_once()
