import pytest
from app.data.api.api import DemoApi

class TestApi:
    def test_get_captcha(self, mocker):
        """Test get_captcha"""
        # Mock time.sleep to speed up test
        mocker.patch('time.sleep')
        
        api = DemoApi()
        res = api.get_captcha()
        
        assert 'data' in res
        assert isinstance(res['data'], str)

    def test_login(self, mocker):
        """Test login"""
        mocker.patch('time.sleep')
        
        api = DemoApi()
        res = api.login("u", "p", "c", "s")
        assert res is True
