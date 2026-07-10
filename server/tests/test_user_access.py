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
