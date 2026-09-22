"""用户邀请裂变与每日剪辑上限激励服务。"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import SystemSetting, User, UserInviteRecord

# 排除易混淆字符 0, O, 1, I, L
INVITE_CODE_CHARS = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
INVITE_CODE_LENGTH = 6

CONFIG_KEY_REWARD_CLIP_LIMIT = "invite_reward_clip_limit"
CONFIG_KEY_MAX_REWARDS_PER_USER = "invite_max_rewards_per_user"
CONFIG_KEY_IS_ENABLED = "invite_feature_enabled"
CONFIG_KEY_REWARD_VALID_DAYS = "invite_reward_valid_days"
CONFIG_KEY_MAX_PERMANENT_CLIP_LIMIT = "invite_max_permanent_clip_limit"

DEFAULT_REWARD_CLIP_LIMIT = 5
DEFAULT_MAX_REWARDS_PER_USER = 0  # 0 表示不限上限
DEFAULT_REWARD_VALID_DAYS = 30  # 默认 30 天，0 表示永久有效
DEFAULT_MAX_PERMANENT_CLIP_LIMIT = 15  # 永久额度上限（默认 15 首，低于此上限的为永久额度，超出部分均为临时额度）


def generate_random_code(length: int = INVITE_CODE_LENGTH) -> str:
    """生成无歧义大写字符邀请码。"""
    return "".join(secrets.choice(INVITE_CODE_CHARS) for _ in range(length))


def ensure_user_invite_code(db: Session, user: User) -> str:
    """确保用户拥有唯一专属邀请码，若无则生成并持久化。"""
    if user.invite_code and user.invite_code.strip():
        return user.invite_code.strip()

    # 尝试生成唯一邀请码，带碰撞自重试机制
    for _ in range(10):
        code = generate_random_code()
        exists = db.scalar(select(func.count(User.id)).where(User.invite_code == code))
        if not exists:
            user.invite_code = code
            db.add(user)
            db.commit()
            db.refresh(user)
            return code

    # 若 6 位极小概率多次冲突，升至 8 位
    code = generate_random_code(8)
    user.invite_code = code
    db.add(user)
    db.commit()
    db.refresh(user)
    return code


def get_invite_config(db: Session) -> dict[str, Any]:
    """读取后台全局邀请规则配置。"""
    settings_rows = db.scalars(
        select(SystemSetting).where(
            SystemSetting.key.in_(
                [
                    CONFIG_KEY_REWARD_CLIP_LIMIT,
                    CONFIG_KEY_MAX_REWARDS_PER_USER,
                    CONFIG_KEY_IS_ENABLED,
                    CONFIG_KEY_REWARD_VALID_DAYS,
                    CONFIG_KEY_MAX_PERMANENT_CLIP_LIMIT,
                ]
            )
        )
    ).all()
    config_map = {s.key: s.value for s in settings_rows}

    # 单次奖励剪辑上限数（默认 5）
    raw_reward = config_map.get(CONFIG_KEY_REWARD_CLIP_LIMIT)
    try:
        reward_clip_limit = max(1, int(raw_reward)) if raw_reward is not None else DEFAULT_REWARD_CLIP_LIMIT
    except (ValueError, TypeError):
        reward_clip_limit = DEFAULT_REWARD_CLIP_LIMIT

    # 单人最大奖励人数上限（默认 0 不限制）
    raw_max = config_map.get(CONFIG_KEY_MAX_REWARDS_PER_USER)
    try:
        max_rewards = max(0, int(raw_max)) if raw_max is not None else DEFAULT_MAX_REWARDS_PER_USER
    except (ValueError, TypeError):
        max_rewards = DEFAULT_MAX_REWARDS_PER_USER

    # 奖励临时额度有效期天数（默认 30 天，0 表示永久有效）
    raw_valid_days = config_map.get(CONFIG_KEY_REWARD_VALID_DAYS)
    try:
        reward_valid_days = max(0, int(raw_valid_days)) if raw_valid_days is not None else DEFAULT_REWARD_VALID_DAYS
    except (ValueError, TypeError):
        reward_valid_days = DEFAULT_REWARD_VALID_DAYS

    # 永久额度上限（默认 15 首，低于此上限可永久提升，超出部分均为临时额度）
    raw_perm_cap = config_map.get(CONFIG_KEY_MAX_PERMANENT_CLIP_LIMIT)
    try:
        max_permanent_clip_limit = max(0, int(raw_perm_cap)) if raw_perm_cap is not None else DEFAULT_MAX_PERMANENT_CLIP_LIMIT
    except (ValueError, TypeError):
        max_permanent_clip_limit = DEFAULT_MAX_PERMANENT_CLIP_LIMIT

    # 功能开关
    raw_enabled = config_map.get(CONFIG_KEY_IS_ENABLED)
    is_enabled = raw_enabled.lower() != "false" if raw_enabled is not None else True

    return {
        "reward_clip_limit": reward_clip_limit,
        "max_rewards_per_user": max_rewards,
        "reward_valid_days": reward_valid_days,
        "max_permanent_clip_limit": max_permanent_clip_limit,
        "is_enabled": is_enabled,
    }


def set_invite_config(
    db: Session,
    reward_clip_limit: int,
    max_rewards_per_user: int = 0,
    reward_valid_days: int = DEFAULT_REWARD_VALID_DAYS,
    max_permanent_clip_limit: int = DEFAULT_MAX_PERMANENT_CLIP_LIMIT,
    is_enabled: bool = True,
) -> dict[str, Any]:
    """后台更新邀请配置。"""
    reward_clip_limit = max(1, int(reward_clip_limit or DEFAULT_REWARD_CLIP_LIMIT))
    max_rewards_per_user = max(0, int(max_rewards_per_user or 0))
    reward_valid_days = max(
        0, int(reward_valid_days if reward_valid_days is not None else DEFAULT_REWARD_VALID_DAYS)
    )
    max_permanent_clip_limit = max(
        0, int(max_permanent_clip_limit if max_permanent_clip_limit is not None else DEFAULT_MAX_PERMANENT_CLIP_LIMIT)
    )

    configs = {
        CONFIG_KEY_REWARD_CLIP_LIMIT: str(reward_clip_limit),
        CONFIG_KEY_MAX_REWARDS_PER_USER: str(max_rewards_per_user),
        CONFIG_KEY_REWARD_VALID_DAYS: str(reward_valid_days),
        CONFIG_KEY_MAX_PERMANENT_CLIP_LIMIT: str(max_permanent_clip_limit),
        CONFIG_KEY_IS_ENABLED: "true" if is_enabled else "false",
    }

    for k, v in configs.items():
        row = db.scalar(select(SystemSetting).where(SystemSetting.key == k))
        if row:
            row.value = v
        else:
            row = SystemSetting(key=k, value=v)
            db.add(row)
    db.commit()

    return {
        "reward_clip_limit": reward_clip_limit,
        "max_rewards_per_user": max_rewards_per_user,
        "reward_valid_days": reward_valid_days,
        "max_permanent_clip_limit": max_permanent_clip_limit,
        "is_enabled": is_enabled,
    }


def get_user_active_invite_bonus(db: Session, user_id: int, now: datetime | None = None) -> int:
    """计算当前用户处于有效期内的全部邀请奖励临时剪辑上限总和。"""
    if now is None:
        now = datetime.now()

    try:
        # 1. 作为邀请人获得的未过期临时奖励（且当时成功获得了奖励）
        inviter_bonus = int(
            db.scalar(
                select(func.coalesce(func.sum(UserInviteRecord.inviter_temp_reward), 0)).where(
                    UserInviteRecord.inviter_id == user_id,
                    UserInviteRecord.inviter_rewarded.is_(True),
                    or_(
                        UserInviteRecord.inviter_expires_at.is_(None),
                        UserInviteRecord.inviter_expires_at > now,
                    ),
                )
            )
            or 0
        )

        # 2. 作为被邀请人获得的未过期临时奖励
        invitee_bonus = int(
            db.scalar(
                select(func.coalesce(func.sum(UserInviteRecord.invitee_temp_reward), 0)).where(
                    UserInviteRecord.invitee_id == user_id,
                    or_(
                        UserInviteRecord.invitee_expires_at.is_(None),
                        UserInviteRecord.invitee_expires_at > now,
                    ),
                )
            )
            or 0
        )

        return inviter_bonus + invitee_bonus
    except Exception:
        return 0


def get_user_effective_clip_limit(db: Session, user: User, now: datetime | None = None) -> int:
    """计算用户当天的最终有效每日剪辑上限（基础/永久配额 + 有效期内的临时邀请加成）。"""
    base_limit = int(user.daily_clip_limit or 0)
    if base_limit <= 0:
        return 0  # 0 本身表示不限制
    active_bonus = get_user_active_invite_bonus(db, user.id, now=now)
    return base_limit + active_bonus


def get_user_invite_info(
    db: Session, user: User, now: datetime | None = None
) -> dict[str, Any]:
    """获取当前用户在客户端设置页面展示的完整邀请数据。"""
    code = ensure_user_invite_code(db, user)
    config = get_invite_config(db)
    if now is None:
        now = datetime.now()

    # 查询谁邀请了我
    inviter_username = None
    if user.invited_by_id:
        inviter = db.scalar(select(User).where(User.id == user.invited_by_id))
        if inviter:
            inviter_username = inviter.username

    # 查询我成功邀请了多少人
    invitee_count = int(
        db.scalar(
            select(func.count(UserInviteRecord.id)).where(
                UserInviteRecord.inviter_id == user.id
            )
        )
        or 0
    )

    # 历史累计通过邀请获得的所有剪辑上限奖励总和
    total_reward = int(
        db.scalar(
            select(func.coalesce(func.sum(UserInviteRecord.reward_clip_limit), 0)).where(
                UserInviteRecord.inviter_id == user.id,
                UserInviteRecord.inviter_rewarded.is_(True),
            )
        )
        or 0
    )
    if user.invited_by_id:
        my_record = db.scalar(
            select(UserInviteRecord).where(UserInviteRecord.invitee_id == user.id)
        )
        if my_record:
            total_reward += my_record.reward_clip_limit

    active_bonus = get_user_active_invite_bonus(db, user.id, now=now)
    effective_clip_limit = get_user_effective_clip_limit(db, user, now=now)

    return {
        "invite_code": code,
        "has_used_invite": bool(user.invited_by_id),
        "invited_by": inviter_username,
        "invitee_count": invitee_count,
        "total_reward_clips": total_reward,
        "current_reward_per_invite": config["reward_clip_limit"],
        "reward_valid_days": config["reward_valid_days"],
        "max_permanent_clip_limit": config["max_permanent_clip_limit"],
        "active_bonus_clips": active_bonus,
        "max_rewards_per_user": config["max_rewards_per_user"],
        "is_enabled": config["is_enabled"],
        "daily_clip_limit": effective_clip_limit,
    }


def bind_invite_code(db: Session, invitee: User, raw_code: str) -> dict[str, Any]:
    """被邀请人绑定邀请码，低于永久上限的部分增加为永久额度，超出部分作为临时额度。"""
    config = get_invite_config(db)
    if not config["is_enabled"]:
        raise HTTPException(status_code=400, detail="邀请激励活动暂未开启")

    code = (raw_code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="请输入有效的邀请码")

    # 1. 检查被邀请人是否已绑定过邀请人（终身只能绑定一次他人的邀请码）
    if invitee.invited_by_id:
        raise HTTPException(
            status_code=400, detail="您已经使用过邀请码，不可重复兑换"
        )

    # 双重保障：检查流水表中是否已存在该被邀请人
    existing_record = db.scalar(
        select(UserInviteRecord).where(UserInviteRecord.invitee_id == invitee.id)
    )
    if existing_record:
        raise HTTPException(
            status_code=400, detail="您已经使用过邀请码，不可重复兑换"
        )

    # 2. 查询邀请人
    inviter = db.scalar(select(User).where(User.invite_code == code))
    if not inviter:
        raise HTTPException(status_code=404, detail="邀请码不存在，请核对后重试")

    # 3. 拦截自己邀请自己
    if inviter.id == invitee.id:
        raise HTTPException(status_code=400, detail="不能使用自己的邀请码")

    # 4. 拦截互邀环路（若 A 邀请过 B，B 绝不能再绑定 A）
    if inviter.invited_by_id == invitee.id:
        raise HTTPException(status_code=400, detail="双方不可互相绑定邀请码")

    # 5. 检查邀请人账号状态
    if not inviter.is_active:
        raise HTTPException(status_code=400, detail="该邀请码所属账号已停用")

    reward = config["reward_clip_limit"]
    max_limit = config["max_rewards_per_user"]
    valid_days = config["reward_valid_days"]
    max_perm_cap = config["max_permanent_clip_limit"]
    now = datetime.now()

    # 6. 检查邀请人是否已达最大奖励人数限制
    inviter_record_count = int(
        db.scalar(
            select(func.count(UserInviteRecord.id)).where(
                UserInviteRecord.inviter_id == inviter.id,
                UserInviteRecord.inviter_rewarded.is_(True),
            )
        )
        or 0
    )
    inviter_can_reward = (max_limit <= 0) or (inviter_record_count < max_limit)

    # 7. 更新被邀请人绑定关系
    invitee.invited_by_id = inviter.id

    # 8. 判定邀请人奖励分配（低于永久上限增加为永久额度，超过永久上限后全部为临时额度）
    inviter_perm = 0
    inviter_temp = 0
    inviter_expires_at = None

    if inviter_can_reward:
        inviter_headroom = max(0, max_perm_cap - int(inviter.daily_clip_limit or 0))
        inviter_perm = min(reward, inviter_headroom)
        inviter_temp = reward - inviter_perm

        if inviter_perm > 0:
            inviter.daily_clip_limit = int(inviter.daily_clip_limit or 0) + inviter_perm
            db.add(inviter)

        if inviter_temp > 0 and valid_days > 0:
            inviter_expires_at = now + timedelta(days=valid_days)

    # 9. 判定被邀请人奖励分配（低于永久上限增加为永久额度，超过永久上限后全部为临时额度）
    invitee_headroom = max(0, max_perm_cap - int(invitee.daily_clip_limit or 0))
    invitee_perm = min(reward, invitee_headroom)
    invitee_temp = reward - invitee_perm

    if invitee_perm > 0:
        invitee.daily_clip_limit = int(invitee.daily_clip_limit or 0) + invitee_perm

    invitee_expires_at = None
    if invitee_temp > 0 and valid_days > 0:
        invitee_expires_at = now + timedelta(days=valid_days)

    # 10. 记录流水明细
    record = UserInviteRecord(
        inviter_id=inviter.id,
        invitee_id=invitee.id,
        reward_clip_limit=reward,
        valid_days=valid_days,
        expires_at=inviter_expires_at,  # 兼容旧字段
        inviter_rewarded=inviter_can_reward,
        inviter_temp_reward=inviter_temp,
        inviter_expires_at=inviter_expires_at,
        invitee_temp_reward=invitee_temp,
        invitee_expires_at=invitee_expires_at,
    )
    db.add(record)
    db.add(invitee)

    db.commit()
    db.refresh(inviter)
    db.refresh(invitee)

    new_clip_limit = get_user_effective_clip_limit(db, invitee, now=now)
    if invitee_temp > 0:
        valid_desc = f"（其中临时额度有效期 {valid_days} 天）" if valid_days > 0 else "（永久有效）"
    else:
        valid_desc = f"（已提升永久额度至 {invitee.daily_clip_limit} 首）"

    return {
        "ok": True,
        "reward": reward,
        "valid_days": valid_days,
        "expires_at": invitee_expires_at.isoformat() if invitee_expires_at else None,
        "new_clip_limit": new_clip_limit,
        "inviter_username": inviter.username,
        "message": f"兑换成功！双方每日剪辑上限已各增加 +{reward} 首/天{valid_desc}",
    }
