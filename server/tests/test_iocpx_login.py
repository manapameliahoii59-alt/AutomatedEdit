import sys
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.services.iocpx_auth import IocpxAuthError, verify_iocpx_credentials


class _FakeResponse:
    def __init__(self, status_code: int, cookies: dict | None = None, set_cookie: list[str] | None = None):
        self.status_code = status_code
        self.cookies = cookies or {}
        self.headers = _FakeHeaders(set_cookie or [])


class _FakeHeaders:
    def __init__(self, values: list[str]):
        self._values = values

    def get_list(self, name: str):
        if name.lower() == "set-cookie":
            return self._values
        return []


class _FakeClient:
    def __init__(self, *args, **kwargs):
        self.post_calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, path, **kwargs):
        self.post_calls.append((path, kwargs))
        if path == "/merchant/auth/login1":
            return _FakeResponse(200, cookies={"ocpx_session_id": "sess-123"})
        if path == "/merchant/auth/login2":
            return _FakeResponse(200)
        raise AssertionError(f"unexpected path: {path}")


def test_verify_iocpx_credentials_success(monkeypatch):
    monkeypatch.setattr("app.services.iocpx_auth.httpx.Client", _FakeClient)
    session_id = verify_iocpx_credentials("user@example.com", "secret")
    assert session_id == "sess-123"


def test_verify_iocpx_credentials_rejects_bad_password(monkeypatch):
    class _BadLoginClient(_FakeClient):
        def post(self, path, **kwargs):
            if path == "/merchant/auth/login1":
                return _FakeResponse(401)
            return super().post(path, **kwargs)

    monkeypatch.setattr("app.services.iocpx_auth.httpx.Client", _BadLoginClient)
    with pytest.raises(IocpxAuthError, match="易投账号或密码错误"):
        verify_iocpx_credentials("user@example.com", "wrong")


def test_verify_iocpx_credentials_requires_session_cookie(monkeypatch):
    class _NoCookieClient(_FakeClient):
        def post(self, path, **kwargs):
            if path == "/merchant/auth/login1":
                return _FakeResponse(200)
            return super().post(path, **kwargs)

    monkeypatch.setattr("app.services.iocpx_auth.httpx.Client", _NoCookieClient)
    with pytest.raises(IocpxAuthError, match="未获取到会话信息"):
        verify_iocpx_credentials("user@example.com", "secret")
