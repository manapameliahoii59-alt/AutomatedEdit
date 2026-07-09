"""用户每日活动记录（登录、关闭、下载、剪辑）。"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UserDailyActivity

_ACTIVITY_EVENTS = frozenset(
    {"app_login", "app_close", "download_drama", "plan_drama", "clip_drama"}
)


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _load_names(raw: str) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item).strip() for item in data if str(item).strip()]


def _dump_names(names: list[str]) -> str:
    return json.dumps(names, ensure_ascii=False)


def _append_name(names: list[str], name: str) -> list[str]:
    name = name.strip()
    if not name or name in names:
        return names
    names.append(name)
    return names


def _get_or_create_today(db: Session, user_id: int) -> UserDailyActivity:
    today = _today()
    row = db.scalar(
        select(UserDailyActivity).where(
            UserDailyActivity.user_id == user_id,
            UserDailyActivity.activity_date == today,
        )
    )
    if row is not None:
        return row

    row = UserDailyActivity(
        user_id=user_id,
        activity_date=today,
        downloaded_dramas="[]",
        planned_dramas="[]",
        clipped_dramas="[]",
        plan_count=0,
        clip_count=0,
    )
    db.add(row)
    db.flush()
    return row


def record_daily_activity(db: Session, user_id: int, event: str, meta: str = "") -> None:
    if event not in _ACTIVITY_EVENTS:
        return

    row = _get_or_create_today(db, user_id)
    now = datetime.now(timezone.utc)

    if event == "app_login":
        if row.login_at is None:
            row.login_at = now
    elif event == "app_close":
        row.logout_at = now
    elif event == "download_drama":
        names = _load_names(row.downloaded_dramas)
        for part in meta.split(","):
            names = _append_name(names, part)
        row.downloaded_dramas = _dump_names(names)
    elif event == "plan_drama":
        names = _load_names(row.planned_dramas)
        names = _append_name(names, meta)
        row.planned_dramas = _dump_names(names)
        row.plan_count = len(names)
    elif event == "clip_drama":
        names = _load_names(row.clipped_dramas)
        names = _append_name(names, meta)
        row.clipped_dramas = _dump_names(names)
        row.clip_count = len(names)
