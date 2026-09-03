"""用户每日策划/剪辑/下载剧目限额。"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import User
from app.services.daily_activity import _get_or_create_today, _load_names, _today


@dataclass
class DailyQuotaOut:
    activity_date: str
    plan_count: int
    clip_count: int
    download_count: int
    plan_limit: int
    clip_limit: int
    download_limit: int
    download_enabled: bool
    planned_dramas: list[str]
    clipped_dramas: list[str]
    downloaded_dramas: list[str]
    can_plan: bool
    can_clip: bool
    can_download: bool

    def to_dict(self) -> dict:
        return {
            "activity_date": self.activity_date,
            "plan_count": self.plan_count,
            "clip_count": self.clip_count,
            "download_count": self.download_count,
            "plan_limit": self.plan_limit,
            "clip_limit": self.clip_limit,
            "download_limit": self.download_limit,
            "download_enabled": self.download_enabled,
            "planned_dramas": self.planned_dramas,
            "clipped_dramas": self.clipped_dramas,
            "downloaded_dramas": self.downloaded_dramas,
            "can_plan": self.can_plan,
            "can_clip": self.can_clip,
            "can_download": self.can_download,
        }


def _resolve_limit(user_value: int) -> int:
    """0 表示不限制。"""
    return max(0, int(user_value or 0))


def get_user_limits(user: User) -> tuple[int, int, int]:
    return (
        _resolve_limit(user.daily_plan_limit),
        _resolve_limit(user.daily_clip_limit),
        _resolve_limit(getattr(user, "daily_download_limit", 0) or 0),
    )


def _is_download_enabled(user: User) -> bool:
    return bool(getattr(user, "download_enabled", True))


def build_daily_quota(db: Session, user: User) -> DailyQuotaOut:
    plan_limit, clip_limit, download_limit = get_user_limits(user)
    download_enabled = _is_download_enabled(user)
    row = _get_or_create_today(db, user.id)
    planned = _load_names(row.planned_dramas)
    clipped = _load_names(row.clipped_dramas)
    downloaded = _load_names(row.downloaded_dramas)
    plan_count = len(planned)
    clip_count = len(clipped)
    download_count = len(downloaded)
    can_download = download_enabled and (
        download_limit <= 0 or download_count < download_limit
    )
    return DailyQuotaOut(
        activity_date=_today().isoformat(),
        plan_count=plan_count,
        clip_count=clip_count,
        download_count=download_count,
        plan_limit=plan_limit,
        clip_limit=clip_limit,
        download_limit=download_limit,
        download_enabled=download_enabled,
        planned_dramas=planned,
        clipped_dramas=clipped,
        downloaded_dramas=downloaded,
        can_plan=plan_limit <= 0 or plan_count < plan_limit,
        can_clip=clip_limit <= 0 or clip_count < clip_limit,
        can_download=can_download,
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
    elif event == "download_drama":
        if not quota.download_enabled:
            raise HTTPException(status_code=403, detail="当前账号未开通视频下载功能")
        if drama_name in quota.downloaded_dramas:
            return
        if quota.download_limit > 0 and quota.download_count >= quota.download_limit:
            raise HTTPException(
                status_code=429,
                detail=f"今日下载剧目数已达上限（{quota.download_limit} 部）",
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


def can_download_drama(db: Session, user: User, drama_name: str) -> tuple[bool, str]:
    drama_name = (drama_name or "").strip()
    quota = build_daily_quota(db, user)
    if not quota.download_enabled:
        return False, "当前账号未开通视频下载功能"
    if not drama_name:
        return True, ""
    if drama_name in quota.downloaded_dramas:
        return True, ""
    if quota.download_limit > 0 and quota.download_count >= quota.download_limit:
        return False, f"今日下载剧目数已达上限（{quota.download_limit} 部）"
    return True, ""
