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


def test_ensure_authorized_interactive_invalid_shows_019_and_returns_false(monkeypatch):
    svc = AccessControlService()
    monkeypatch.setattr(
        "app.data.services.access_control_service.get_api",
        lambda: _FakeApi("invalid"),
    )
    dialog_calls = []
    monkeypatch.setattr(
        "app.common.utils.show_dialog",
        lambda parent, content, title: dialog_calls.append((content, title)),
    )

    res = svc.ensure_authorized_interactive()
    assert res is False
    assert svc.is_blocked() is True
    assert len(dialog_calls) == 1
    assert "错误代码：019" in dialog_calls[0][0]


def test_ensure_authorized_interactive_valid_returns_true(monkeypatch):
    svc = AccessControlService()
    monkeypatch.setattr(
        "app.data.services.access_control_service.get_api",
        lambda: _FakeApi("valid"),
    )
    res = svc.ensure_authorized_interactive()
    assert res is True
    assert svc.is_blocked() is False

