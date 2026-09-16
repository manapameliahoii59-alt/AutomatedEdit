import pytest
from app.data.api.api import RemoteApi, ApiError
from app.data.services.access_control_service import AccessControlService


def test_api_check_session_returns_expired_on_401(monkeypatch):
    api = RemoteApi(base_url="http://fake")
    api._token = "some-token"

    def mock_request(method, path, **kwargs):
        raise ApiError("登录已过期，请重新登录", status_code=401)

    monkeypatch.setattr(api, "_request", mock_request)
    assert api.check_session() == "expired"


def test_api_check_session_returns_invalid_on_403(monkeypatch):
    api = RemoteApi(base_url="http://fake")
    api._token = "some-token"

    def mock_request(method, path, **kwargs):
        raise ApiError("无效", status_code=403)

    monkeypatch.setattr(api, "_request", mock_request)
    assert api.check_session() == "invalid"


def test_access_control_notifies_callback_on_session_expired(monkeypatch):
    service = AccessControlService()
    fake_api = type("FakeApi", (), {})()
    fake_api.check_session = lambda: "expired"

    monkeypatch.setattr("app.data.services.access_control_service.get_api", lambda: fake_api)

    notified = []
    service.register_session_expired_callback(lambda reason: notified.append(reason))

    result = service.refresh()
    assert result is False
    assert service.is_blocked() is True
    assert len(notified) == 1
    assert "过期" in notified[0]


def test_auth_service_try_auto_login_fails_on_expired(monkeypatch):
    from app.data.services.auth_service import AuthService
    from app.common.aes import aes_encrypt
    from app.common.config import cfg

    auth = AuthService()
    cfg.access_token.value = aes_encrypt("fake_token")

    fake_api = type("FakeApi", (), {})()
    fake_api.check_session = lambda: "expired"

    monkeypatch.setattr("app.data.services.auth_service.get_api", lambda: fake_api)

    assert auth.try_auto_login() is False

