from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import UsageEvent, User, UserDailyActivity, UserSecret
from app.schemas import (
    DailyActivityOut,
    DailyQuotaOut,
    QuotaCheckOut,
    QuotaCheckRequest,
    SecretsOut,
    UsageReport,
    UserSettingsOut,
    UserSettingsPatch,
)
from app.services.daily_activity import record_daily_activity
from app.services.daily_quota import assert_can_record, build_daily_quota, can_clip_drama, can_plan_drama
from app.services.user_settings import get_user_settings, patch_user_settings

router = APIRouter(prefix="/api/client", tags=["client"])


def _quota_to_schema(quota) -> DailyQuotaOut:
    return DailyQuotaOut(
        activity_date=date.fromisoformat(quota.activity_date),
        plan_count=quota.plan_count,
        clip_count=quota.clip_count,
        plan_limit=quota.plan_limit,
        clip_limit=quota.clip_limit,
        planned_dramas=quota.planned_dramas,
        clipped_dramas=quota.clipped_dramas,
        can_plan=quota.can_plan,
        can_clip=quota.can_clip,
    )


@router.get("/secrets", response_model=SecretsOut)
def get_secrets(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(UserSecret).filter(UserSecret.user_id == user.id).first()
    if row is None:
        return SecretsOut()
    return SecretsOut(deepseek_keys=row.deepseek_keys or "", dashscope_key=row.dashscope_key or "")


@router.post("/usage", status_code=201)
def report_usage(
    body: UsageReport,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.event in {"plan_drama", "clip_drama"}:
        assert_can_record(db, user, body.event, body.meta or "")

    event = UsageEvent(
        user_id=user.id,
        event=body.event,
        success=body.success,
        duration_ms=max(0, body.duration_ms),
        meta=body.meta or "",
        client_version=body.client_version or "",
    )
    db.add(event)
    record_daily_activity(db, user.id, body.event, body.meta or "")
    db.commit()
    return {"ok": True}


@router.get("/quota/today", response_model=DailyQuotaOut)
def get_today_quota(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _quota_to_schema(build_daily_quota(db, user))


@router.post("/quota/check", response_model=QuotaCheckOut)
def check_quota(
    body: QuotaCheckRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    quota = build_daily_quota(db, user)
    if body.action == "plan":
        allowed, message = can_plan_drama(db, user, body.drama_name)
    else:
        allowed, message = can_clip_drama(db, user, body.drama_name)
    return QuotaCheckOut(
        allowed=allowed,
        message=message,
        quota=_quota_to_schema(quota),
    )


@router.get("/activity/today", response_model=DailyActivityOut | None)
def get_today_activity(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).date()
    row = (
        db.query(UserDailyActivity)
        .filter(UserDailyActivity.user_id == user.id, UserDailyActivity.activity_date == today)
        .first()
    )
    if row is None:
        return None
    return DailyActivityOut.model_validate(row)


@router.get("/settings", response_model=UserSettingsOut)
def get_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return get_user_settings(db, user.id)


@router.patch("/settings", response_model=UserSettingsOut)
def update_settings(
    body: UserSettingsPatch,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    patch = body.model_dump(exclude_unset=True)
    result = patch_user_settings(db, user.id, patch)
    db.commit()
    return result
