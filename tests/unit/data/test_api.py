import requests
import pytest
from app.data.api.api import DemoApi, RemoteApi, ApiError


class TestDemoApi:
    def test_login_rejected(self):
        api = DemoApi()
        with pytest.raises(ApiError, match="未配置服务端"):
            api.login("u", "p")


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
        mocker.patch.object(api._session, 'request', return_value=mock_resp)

        result = api.login('u', 'p')
        assert result.access_token == 'tok'
        assert result.username == 'u'

    def test_login_http_error(self, mocker):
        api = RemoteApi('https://api.test.com')
        mock_resp = mocker.Mock()
        mock_resp.status_code = 401
        mock_resp.text = 'bad'
        mock_resp.json.side_effect = ValueError()
        mocker.patch.object(api._session, 'request', return_value=mock_resp)

        with pytest.raises(ApiError):
            api.login('u', 'wrong')

    def test_connect_timeout_hides_server_address(self, mocker):
        api = RemoteApi('http://129.204.86.63:7172')
        mocker.patch.object(
            api._session,
            'request',
            side_effect=requests.exceptions.ConnectTimeout('boom'),
        )

        with pytest.raises(ApiError) as excinfo:
            api._request('GET', '/api/auth/me')

        msg = str(excinfo.value)
        assert '无法连接服务器' in msg
        assert '129.204.86.63' not in msg
        assert 'http://' not in msg
        # 技术细节保留在 detail 中，仅用于日志/排查
        assert '129.204.86.63' in excinfo.value.detail
