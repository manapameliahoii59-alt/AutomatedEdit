"""用户桌面端访问权限（启用状态 + 使用期限）。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.models import User

INVALID_USER_MESSAGE = "无效"


def is_user_allowed(user: User, *, today=None) -> bool:
    if not user.is_active:
        return False
    valid_until = getattr(user, "valid_until", None)
    if valid_until is None:
        return True
    if today is None:
        today = datetime.now(timezone.utc).date()
    return valid_until >= today


def assert_user_allowed(user: User) -> None:
    if not is_user_allowed(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=INVALID_USER_MESSAGE,
        )
