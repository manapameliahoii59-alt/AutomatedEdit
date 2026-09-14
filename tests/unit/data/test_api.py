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

    def test_report_usage_payload(self, mocker):
        api = RemoteApi('https://api.test.com')
        api._token = 'test-token'
        mock_request = mocker.patch.object(api, '_request')

        api.report_usage(
            'batch_all_render',
            success=True,
            duration_ms=55000,
            meta='测试剧',
            plan_mode='mixed',
            plan_model='mimo-v2.5',
            transcribe_ms=10000,
            plan_ms=20000,
            render_ms=25000,
            encoder='h264_nvenc',
            resolution='720x1280',
            cache_ms=1000,
            compose_ms=2000,
            render_engine='current',
        )

        mock_request.assert_called_once()
        args, kwargs = mock_request.call_args
        assert args == ('POST', '/api/client/usage')
        payload = kwargs['json']
        assert payload['event'] == 'batch_all_render'
        assert payload['success'] is True
        assert payload['duration_ms'] == 55000
        assert payload['meta'] == '测试剧'
        assert payload['plan_mode'] == 'mixed'
        assert payload['plan_model'] == 'mimo-v2.5'
        assert payload['transcribe_ms'] == 10000
        assert payload['plan_ms'] == 20000
        assert payload['render_ms'] == 25000
        assert payload['encoder'] == 'h264_nvenc'
        assert payload['resolution'] == '720x1280'
        assert payload['cache_ms'] == 1000
        assert payload['compose_ms'] == 2000
        assert payload['render_engine'] == 'current'
