"""用户策划解密密钥管理。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.config import settings
from app.models import UserSecret
from app.services.plan_crypto import generate_plan_decrypt_key


def ensure_user_secret(db: Session, user_id: int) -> UserSecret:
    row = db.query(UserSecret).filter(UserSecret.user_id == user_id).first()
    if row is None:
        row = UserSecret(
            user_id=user_id,
            plan_decrypt_key=generate_plan_decrypt_key(),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    if not (row.plan_decrypt_key or "").strip():
        row.plan_decrypt_key = generate_plan_decrypt_key()
        db.commit()
        db.refresh(row)
    return row


def resolve_deepseek_keys(db: Session, user_id: int) -> str:
    """优先使用管理后台为用户配置的 DeepSeek Key，其次才读 .env。"""
    row = ensure_user_secret(db, user_id)
    user_keys = (row.deepseek_keys or "").strip()
    if user_keys:
        return user_keys
    return (settings.deepseek_api_keys or "").strip()
