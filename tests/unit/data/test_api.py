import pytest
from app.data.api.api import DemoApi, RemoteApi, ApiError


class TestDemoApi:
    def test_login(self, mocker):
        mocker.patch('time.sleep')
        api = DemoApi()
        result = api.login("u", "p")
        assert result.username == "u"


class TestRemoteApi:
    def test_login_success(self, mocker):
        mocker.patch('app.data.api.api.cfg')
        from app.data.api.api import cfg
        cfg.api_base_url.value = ''

        api = RemoteApi('https://api.test.com')
        mock_resp = mocker.Mock()
        mock_resp.status_code = 200
        mock_resp.content = b'{"access_token":"tok","user":{"username":"u","role":"user"}}'
        mock_resp.json.return_value = {
            'access_token': 'tok',
            'user': {'username': 'u', 'role': 'user'},
        }
        mocker.patch('requests.request', return_value=mock_resp)

        result = api.login('u', 'p')
        assert result.access_token == 'tok'
        assert result.username == 'u'

    def test_login_http_error(self, mocker):
        api = RemoteApi('https://api.test.com')
        mock_resp = mocker.Mock()
        mock_resp.status_code = 401
        mock_resp.text = 'bad'
        mock_resp.json.side_effect = ValueError()
        mocker.patch('requests.request', return_value=mock_resp)

        with pytest.raises(ApiError):
            api.login('u', 'wrong')
