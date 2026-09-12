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


class TestResolveBaseUrl:
    def _patch_cfg(self, mocker, base_url):
        mocker.patch('app.data.api.api.cfg')
        from app.data.api.api import cfg

        cfg.api_base_url.value = base_url

    def test_dev_defaults_local(self, monkeypatch, mocker):
        monkeypatch.delenv('AE_API_BASE_URL', raising=False)
        self._patch_cfg(mocker, '')
        mocker.patch('app.data.api.api.is_dev_runtime', return_value=True)

        from app.data.api.api import _resolve_base_url

        assert _resolve_base_url() == 'http://127.0.0.1:8000'

    def test_packaged_defaults_prod(self, monkeypatch, mocker):
        monkeypatch.delenv('AE_API_BASE_URL', raising=False)
        self._patch_cfg(mocker, '')
        mocker.patch('app.data.api.api.is_dev_runtime', return_value=False)

        from app.data.api.api import _resolve_base_url

        assert _resolve_base_url() == 'http://129.204.86.63:7172'

    def test_env_overrides_config_and_default(self, monkeypatch, mocker):
        monkeypatch.setenv('AE_API_BASE_URL', 'http://env.example.com/')
        self._patch_cfg(mocker, 'http://config.example.com')
        mocker.patch('app.data.api.api.is_dev_runtime', return_value=False)

        from app.data.api.api import _resolve_base_url

        assert _resolve_base_url() == 'http://env.example.com'

    def test_config_overrides_default(self, monkeypatch, mocker):
        monkeypatch.delenv('AE_API_BASE_URL', raising=False)
        self._patch_cfg(mocker, 'http://config.example.com/')
        mocker.patch('app.data.api.api.is_dev_runtime', return_value=False)

        from app.data.api.api import _resolve_base_url

        assert _resolve_base_url() == 'http://config.example.com'
