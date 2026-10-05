"""用户邀请裂变与每日剪辑上限激励服务。"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import SystemSetting, User, UserDailyActivity, UserInviteRecord
from app.services.daily_activity import _load_names

# 排除易混淆字符 0, O, 1, I, L
INVITE_CODE_CHARS = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
INVITE_CODE_LENGTH = 6

CONFIG_KEY_REWARD_CLIP_LIMIT = "invite_reward_clip_limit"
CONFIG_KEY_MAX_REWARDS_PER_USER = "invite_max_rewards_per_user"
CONFIG_KEY_IS_ENABLED = "invite_feature_enabled"
CONFIG_KEY_REWARD_VALID_DAYS = "invite_reward_valid_days"
CONFIG_KEY_MAX_PERMANENT_CLIP_LIMIT = "invite_max_permanent_clip_limit"
CONFIG_KEY_REQUIRE_INVITEE_CLIPS = "invite_require_invitee_clips"

DEFAULT_REWARD_CLIP_LIMIT = 5
DEFAULT_MAX_REWARDS_PER_USER = 0  # 0 表示不限上限
DEFAULT_REWARD_VALID_DAYS = 30  # 默认 30 天，0 表示永久有效
DEFAULT_MAX_PERMANENT_CLIP_LIMIT = 15  # 永久额度上限（默认 15 首，低于此上限的为永久额度，超出部分均为临时额度）
DEFAULT_REQUIRE_INVITEE_CLIPS = 10  # 被邀请人需成功剪辑的剧目数，达标后双方奖励才生效；0 表示立即生效


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
                    CONFIG_KEY_REQUIRE_INVITEE_CLIPS,
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

    # 被邀请人需成功剪辑的剧目数（默认 10，0 表示立即生效）
    raw_require = config_map.get(CONFIG_KEY_REQUIRE_INVITEE_CLIPS)
    try:
        require_invitee_clips = (
            max(0, int(raw_require))
            if raw_require is not None
            else DEFAULT_REQUIRE_INVITEE_CLIPS
        )
    except (ValueError, TypeError):
        require_invitee_clips = DEFAULT_REQUIRE_INVITEE_CLIPS

    return {
        "reward_clip_limit": reward_clip_limit,
        "max_rewards_per_user": max_rewards,
        "reward_valid_days": reward_valid_days,
        "max_permanent_clip_limit": max_permanent_clip_limit,
        "require_invitee_clips": require_invitee_clips,
        "is_enabled": is_enabled,
    }


def set_invite_config(
    db: Session,
    reward_clip_limit: int,
    max_rewards_per_user: int = 0,
    reward_valid_days: int = DEFAULT_REWARD_VALID_DAYS,
    max_permanent_clip_limit: int = DEFAULT_MAX_PERMANENT_CLIP_LIMIT,
    require_invitee_clips: int = DEFAULT_REQUIRE_INVITEE_CLIPS,
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
    require_invitee_clips = max(
        0, int(require_invitee_clips if require_invitee_clips is not None else DEFAULT_REQUIRE_INVITEE_CLIPS)
    )

    configs = {
        CONFIG_KEY_REWARD_CLIP_LIMIT: str(reward_clip_limit),
        CONFIG_KEY_MAX_REWARDS_PER_USER: str(max_rewards_per_user),
        CONFIG_KEY_REWARD_VALID_DAYS: str(reward_valid_days),
        CONFIG_KEY_MAX_PERMANENT_CLIP_LIMIT: str(max_permanent_clip_limit),
        CONFIG_KEY_REQUIRE_INVITEE_CLIPS: str(require_invitee_clips),
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
        "require_invitee_clips": require_invitee_clips,
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


def get_user_total_clipped_dramas(db: Session, user_id: int) -> int:
    """累计成功剪辑的不同剧目数（跨天去重）。"""
    rows = db.scalars(
        select(UserDailyActivity).where(UserDailyActivity.user_id == user_id)
    ).all()
    names: set[str] = set()
    for row in rows:
        for name in _load_names(row.clipped_dramas):
            names.add(name)
    return len(names)


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

    # 历史累计通过邀请获得的所有剪辑上限奖励总和（仅统计已生效记录）
    total_reward = int(
        db.scalar(
            select(func.coalesce(func.sum(UserInviteRecord.reward_clip_limit), 0)).where(
                UserInviteRecord.inviter_id == user.id,
                UserInviteRecord.inviter_rewarded.is_(True),
            )
        )
        or 0
    )

    my_record = None
    if user.invited_by_id:
        my_record = db.scalar(
            select(UserInviteRecord).where(UserInviteRecord.invitee_id == user.id)
        )
        if my_record and getattr(my_record, "invitee_qualified", False):
            total_reward += my_record.reward_clip_limit

    required = int(
        config.get("require_invitee_clips", DEFAULT_REQUIRE_INVITEE_CLIPS) or 0
    )
    clip_progress = get_user_total_clipped_dramas(db, user.id)
    invitee_qualified = (
        bool(getattr(my_record, "invitee_qualified", False)) if my_record else True
    )
    remaining = (
        max(0, required - clip_progress)
        if (my_record is not None and required > 0 and not invitee_qualified)
        else 0
    )

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
        "require_invitee_clips": required,
        "invitee_clip_progress": clip_progress,
        "invitee_remaining_clips": remaining,
        "invitee_qualified": invitee_qualified,
    }


def _inviter_rewarded_count(db: Session, inviter_id: int) -> int:
    return int(
        db.scalar(
            select(func.count(UserInviteRecord.id)).where(
                UserInviteRecord.inviter_id == inviter_id,
                UserInviteRecord.inviter_rewarded.is_(True),
            )
        )
        or 0
    )


def _apply_invite_reward(
    db: Session,
    record: UserInviteRecord,
    config: dict[str, Any],
) -> bool:
    """被邀请人达标后发放双方奖励（永久/临时额度分配），幂等。"""
    if getattr(record, "invitee_qualified", False):
        return False

    inviter = db.get(User, record.inviter_id)
    invitee = db.get(User, record.invitee_id)
    if inviter is None or invitee is None:
        return False

    reward = int(record.reward_clip_limit or config["reward_clip_limit"])
    valid_days = int(
        record.valid_days
        if record.valid_days is not None
        else config["reward_valid_days"]
    )
    max_perm_cap = int(config["max_permanent_clip_limit"])
    max_limit = int(config["max_rewards_per_user"])
    now = datetime.now()

    # 邀请人是否还能拿奖励（奖励人数上限）
    inviter_can_reward = (max_limit <= 0) or (
        _inviter_rewarded_count(db, inviter.id) < max_limit
    )

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

    invitee_headroom = max(0, max_perm_cap - int(invitee.daily_clip_limit or 0))
    invitee_perm = min(reward, invitee_headroom)
    invitee_temp = reward - invitee_perm
    if invitee_perm > 0:
        invitee.daily_clip_limit = int(invitee.daily_clip_limit or 0) + invitee_perm
        db.add(invitee)
    invitee_expires_at = None
    if invitee_temp > 0 and valid_days > 0:
        invitee_expires_at = now + timedelta(days=valid_days)

    record.inviter_rewarded = bool(inviter_can_reward)
    record.inviter_temp_reward = inviter_temp
    record.inviter_expires_at = inviter_expires_at
    record.invitee_temp_reward = invitee_temp
    record.invitee_expires_at = invitee_expires_at
    record.expires_at = inviter_expires_at  # 兼容旧字段
    record.invitee_qualified = True
    db.add(record)
    db.commit()
    db.refresh(inviter)
    db.refresh(invitee)
    return True


def maybe_qualify_invite_reward(db: Session, invitee_id: int) -> bool:
    """被邀请人剪辑达标后发放邀请奖励；未达标/无待生效记录时返回 False。"""
    record = db.scalar(
        select(UserInviteRecord).where(UserInviteRecord.invitee_id == invitee_id)
    )
    if record is None or getattr(record, "invitee_qualified", False):
        return False
    config = get_invite_config(db)
    required = int(
        config.get("require_invitee_clips", DEFAULT_REQUIRE_INVITEE_CLIPS) or 0
    )
    if required > 0 and get_user_total_clipped_dramas(db, invitee_id) < required:
        return False
    return _apply_invite_reward(db, record, config)


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
    valid_days = config["reward_valid_days"]
    now = datetime.now()
    required = int(
        config.get("require_invitee_clips", DEFAULT_REQUIRE_INVITEE_CLIPS) or 0
    )

    # 6. 更新被邀请人绑定关系，先创建“待生效”流水（双方奖励暂不发放）
    invitee.invited_by_id = inviter.id
    record = UserInviteRecord(
        inviter_id=inviter.id,
        invitee_id=invitee.id,
        reward_clip_limit=reward,
        valid_days=valid_days,
        expires_at=None,  # 兼容旧字段，生效时回填
        inviter_rewarded=False,
        invitee_qualified=False,
        inviter_temp_reward=0,
        inviter_expires_at=None,
        invitee_temp_reward=0,
        invitee_expires_at=None,
    )
    db.add(record)
    db.add(invitee)
    db.commit()
    db.refresh(record)

    # 7. 立即生效（规则为 0）或达标即生效（被邀请人已有足够剪辑量）
    if required <= 0:
        _apply_invite_reward(db, record, config)
    else:
        maybe_qualify_invite_reward(db, invitee.id)

    db.refresh(record)
    db.refresh(invitee)
    new_clip_limit = get_user_effective_clip_limit(db, invitee, now=now)

    if getattr(record, "invitee_qualified", False):
        if record.invitee_temp_reward > 0:
            valid_desc = (
                f"（其中临时额度有效期 {valid_days} 天）"
                if valid_days > 0
                else "（永久有效）"
            )
        else:
            valid_desc = f"（已提升永久额度至 {invitee.daily_clip_limit} 首）"
        message = f"兑换成功！双方每日剪辑上限已各增加 +{reward} 首/天{valid_desc}"
    else:
        progress = get_user_total_clipped_dramas(db, invitee.id)
        message = (
            f"绑定成功！被邀请方成功剪辑满 {required} 部剧后，"
            f"双方每日剪辑上限各 +{reward} 首才会生效（当前已剪辑 {progress}/{required} 部）"
        )

    return {
        "ok": True,
        "reward": reward,
        "valid_days": valid_days,
        "expires_at": record.invitee_expires_at.isoformat()
        if record.invitee_expires_at
        else None,
        "new_clip_limit": new_clip_limit,
        "inviter_username": inviter.username,
        "message": message,
    }
