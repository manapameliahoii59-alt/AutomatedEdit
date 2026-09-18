import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.models import User
from app.services.user_access import INVALID_USER_MESSAGE, assert_user_allowed, is_user_allowed


def _user(*, active=True, valid_until=None) -> User:
    return User(
        username="demo",
        password_hash="x",
        is_active=active,
        valid_until=valid_until,
    )


def test_user_allowed_when_no_expiry():
    assert is_user_allowed(_user(), today=date(2026, 7, 10)) is True


def test_user_not_allowed_when_expired():
    user = _user(valid_until=date(2026, 7, 9))
    assert is_user_allowed(user, today=date(2026, 7, 10)) is False


def test_user_allowed_on_last_valid_day():
    user = _user(valid_until=date(2026, 7, 10))
    assert is_user_allowed(user, today=date(2026, 7, 10)) is True


def test_assert_user_allowed_raises_invalid():
    user = _user(active=False)
    with pytest.raises(HTTPException) as exc:
        assert_user_allowed(user)
    assert exc.value.status_code == 403
    assert exc.value.detail == INVALID_USER_MESSAGE


def test_login_single_active_session_kickout():
    from app.auth import create_access_token
    from app.deps import get_current_user
    from fastapi.security import HTTPAuthorizationCredentials

    user = User(id=1, username="test@example.com", password_hash="hash", plain_password="pwd", is_active=True, token_version=1)
    token1 = create_access_token(user.id, user.username, user.role, token_version=user.token_version)

    class FakeDB:
        def get(self, model, user_id):
            return user

    u1 = get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token1), db=FakeDB(), client_version="0.0.20")
    assert u1.id == 1

    # 另一台设备登录导致 token_version 自增
    user.token_version += 1
    token2 = create_access_token(user.id, user.username, user.role, token_version=user.token_version)

    # 新设备正常工作
    u2 = get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token2), db=FakeDB(), client_version="0.0.20")
    assert u2.id == 1

    # 旧设备 Token 1 立即被踢下线，返回 401
    with pytest.raises(HTTPException) as exc:
        get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token1), db=FakeDB(), client_version="0.0.20")
    assert exc.value.status_code == 401
    assert "另一台设备" in exc.value.detail

