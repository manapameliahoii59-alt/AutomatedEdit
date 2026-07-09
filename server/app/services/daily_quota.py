"""用户每日策划/剪辑剧目限额。"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import User, UserDailyActivity
from app.services.daily_activity import _get_or_create_today, _load_names, _today


@dataclass
class DailyQuotaOut:
    activity_date: str
    plan_count: int
    clip_count: int
    plan_limit: int
    clip_limit: int
    planned_dramas: list[str]
    clipped_dramas: list[str]
    can_plan: bool
    can_clip: bool

    def to_dict(self) -> dict:
        return {
            "activity_date": self.activity_date,
            "plan_count": self.plan_count,
            "clip_count": self.clip_count,
            "plan_limit": self.plan_limit,
            "clip_limit": self.clip_limit,
            "planned_dramas": self.planned_dramas,
            "clipped_dramas": self.clipped_dramas,
            "can_plan": self.can_plan,
            "can_clip": self.can_clip,
        }


def _resolve_limit(user_value: int) -> int:
    """0 表示不限制。"""
    return max(0, int(user_value or 0))


def get_user_limits(user: User) -> tuple[int, int]:
    return _resolve_limit(user.daily_plan_limit), _resolve_limit(user.daily_clip_limit)


def _can_add_drama(names: list[str], drama_name: str, limit: int) -> bool:
    drama_name = (drama_name or "").strip()
    if not drama_name:
        return True
    if drama_name in names:
        return True
    if limit <= 0:
        return True
    return len(names) < limit


def build_daily_quota(db: Session, user: User) -> DailyQuotaOut:
    plan_limit, clip_limit = get_user_limits(user)
    row = _get_or_create_today(db, user.id)
    planned = _load_names(row.planned_dramas)
    clipped = _load_names(row.clipped_dramas)
    plan_count = len(planned)
    clip_count = len(clipped)
    return DailyQuotaOut(
        activity_date=_today().isoformat(),
        plan_count=plan_count,
        clip_count=clip_count,
        plan_limit=plan_limit,
        clip_limit=clip_limit,
        planned_dramas=planned,
        clipped_dramas=clipped,
        can_plan=plan_limit <= 0 or plan_count < plan_limit,
        can_clip=clip_limit <= 0 or clip_count < clip_limit,
    )


def assert_can_record(db: Session, user: User, event: str, drama_name: str) -> None:
    drama_name = (drama_name or "").strip()
    if not drama_name:
        return

    quota = build_daily_quota(db, user)
    if event == "plan_drama":
        if drama_name in quota.planned_dramas:
            return
        if quota.plan_limit > 0 and quota.plan_count >= quota.plan_limit:
            raise HTTPException(
                status_code=429,
                detail=f"今日策划剧目数已达上限（{quota.plan_limit} 部）",
            )
    elif event == "clip_drama":
        if drama_name in quota.clipped_dramas:
            return
        if quota.clip_limit > 0 and quota.clip_count >= quota.clip_limit:
            raise HTTPException(
                status_code=429,
                detail=f"今日剪辑剧目数已达上限（{quota.clip_limit} 部）",
            )


def can_plan_drama(db: Session, user: User, drama_name: str) -> tuple[bool, str]:
    drama_name = (drama_name or "").strip()
    if not drama_name:
        return True, ""
    quota = build_daily_quota(db, user)
    if drama_name in quota.planned_dramas:
        return True, ""
    if quota.plan_limit > 0 and quota.plan_count >= quota.plan_limit:
        return False, f"今日策划剧目数已达上限（{quota.plan_limit} 部）"
    return True, ""


def can_clip_drama(db: Session, user: User, drama_name: str) -> tuple[bool, str]:
    drama_name = (drama_name or "").strip()
    if not drama_name:
        return True, ""
    quota = build_daily_quota(db, user)
    if drama_name in quota.clipped_dramas:
        return True, ""
    if quota.clip_limit > 0 and quota.clip_count >= quota.clip_limit:
        return False, f"今日剪辑剧目数已达上限（{quota.clip_limit} 部）"
    return True, ""
