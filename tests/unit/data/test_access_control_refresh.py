"""AccessControl：网络不可达时不应误封禁。"""

from app.data.api.api import ApiError
from app.data.services.access_control_service import AccessControlService


class _FakeApi:
    def __init__(self, status: str):
        self._status = status

    def check_session(self) -> str:
        return self._status


def test_refresh_unreachable_keeps_unblocked(monkeypatch):
    svc = AccessControlService()
    svc.unblock()
    monkeypatch.setattr(
        "app.data.services.access_control_service.get_api",
        lambda: _FakeApi("unreachable"),
    )
    assert svc.refresh() is True
    assert not svc.is_blocked()


def test_refresh_unreachable_clears_false_block(monkeypatch):
    svc = AccessControlService()
    svc.block()
    monkeypatch.setattr(
        "app.data.services.access_control_service.get_api",
        lambda: _FakeApi("unreachable"),
    )
    assert svc.refresh() is True
    assert not svc.is_blocked()


def test_refresh_invalid_blocks(monkeypatch):
    svc = AccessControlService()
    svc.unblock()
    monkeypatch.setattr(
        "app.data.services.access_control_service.get_api",
        lambda: _FakeApi("invalid"),
    )
    assert svc.refresh() is False
    assert svc.is_blocked()


def test_refresh_valid_unblocks(monkeypatch):
    svc = AccessControlService()
    svc.block()
    monkeypatch.setattr(
        "app.data.services.access_control_service.get_api",
        lambda: _FakeApi("valid"),
    )
    assert svc.refresh() is True
    assert not svc.is_blocked()


def test_check_session_network_error_is_unreachable(monkeypatch):
    from app.data.api.api import RemoteApi

    api = RemoteApi("http://example.invalid")
    api.set_token("tok")

    def _boom(*_a, **_k):
        raise ApiError("无法连接服务器（连接超时）：x")

    monkeypatch.setattr(api, "_request", _boom)
    assert api.check_session() == "unreachable"
