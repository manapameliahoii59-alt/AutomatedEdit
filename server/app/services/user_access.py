"""用户桌面端访问权限（启用状态 + 使用期限）。"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User

INVALID_USER_MESSAGE = "无效"


def is_user_allowed(user: User, *, today=None, db: Session | None = None) -> bool:
    """检查用户是否允许使用桌面端。

    若用户设置了有效期限且已逾期（valid_until < today），自动将用户 is_active 置为 False，
    递增 token_version 强制阻断现存会话，并持久化到数据库。
    """
    if not user.is_active:
        return False
    valid_until = getattr(user, "valid_until", None)
    if valid_until is None:
        return True
    if today is None:
        today = datetime.now(timezone.utc).date()
    if valid_until < today:
        # 已过期：自动关闭桌面端权限
        user.is_active = False
        user.token_version = (getattr(user, "token_version", 1) or 1) + 1
        if db is not None:
            try:
                db.commit()
                db.refresh(user)
            except Exception:
                db.rollback()
        return False
    return True


def assert_user_allowed(user: User, *, db: Session | None = None) -> None:
    if not is_user_allowed(user, db=db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=INVALID_USER_MESSAGE,
        )


def sync_expired_users(db: Session, *, today=None) -> int:
    """批量扫描并同步所有已过有效期的用户，将其 is_active 自动更新为 False 并失效 Token。"""
    if today is None:
        today = datetime.now(timezone.utc).date()
    expired = db.scalars(
        select(User).where(
            User.valid_until.is_not(None),
            User.valid_until < today,
            User.is_active.is_(True),
        )
    ).all()
    count = len(expired)
    if count > 0:
        for u in expired:
            u.is_active = False
            u.token_version = (getattr(u, "token_version", 1) or 1) + 1
        try:
            db.commit()
        except Exception:
            db.rollback()
    return count
