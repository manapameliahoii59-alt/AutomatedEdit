from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import UsageEvent, User, UserDailyActivity
from app.schemas import (
    ClientVersionOut,
    DailyActivityOut,
    DailyQuotaOut,
    PlanJobCreateRequest,
    PlanJobCreateResponse,
    PlanJobResultOut,
    PlanJobStatusOut,
    QuotaCheckOut,
    QuotaCheckRequest,
    SecretsOut,
    UsageReport,
    UserSettingsOut,
    UserSettingsPatch,
)
from app.services.client_version import build_client_version_out
from app.services.daily_activity import record_daily_activity
from app.services.daily_quota import (
    assert_can_record,
    build_daily_quota,
    can_clip_drama,
    can_download_drama,
    can_plan_drama,
)
from app.services.plan_jobs import create_plan_job, get_plan_job, user_facing_plan_error
from app.services.plan_secrets import ensure_user_secret
from app.services.user_settings import get_user_settings, patch_user_settings

router = APIRouter(prefix="/api/client", tags=["client"])


@router.get("/version", response_model=ClientVersionOut)
def get_client_version(request: Request):
    """桌面端检查更新（无需登录）。优先读 release/version.json。"""
    return build_client_version_out(request)


def _quota_to_schema(quota) -> DailyQuotaOut:
    return DailyQuotaOut(
        activity_date=date.fromisoformat(quota.activity_date),
        plan_count=quota.plan_count,
        clip_count=quota.clip_count,
        download_count=quota.download_count,
        plan_limit=quota.plan_limit,
        clip_limit=quota.clip_limit,
        download_limit=quota.download_limit,
        download_enabled=quota.download_enabled,
        planned_dramas=quota.planned_dramas,
        clipped_dramas=quota.clipped_dramas,
        downloaded_dramas=quota.downloaded_dramas,
        can_plan=quota.can_plan,
        can_clip=quota.can_clip,
        can_download=quota.can_download,
    )


@router.get("/secrets", response_model=SecretsOut)
def get_secrets(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = ensure_user_secret(db, user.id)
    return SecretsOut(
        deepseek_keys=row.deepseek_keys or "",
        dashscope_key=row.dashscope_key or "",
        plan_decrypt_key=row.plan_decrypt_key or "",
    )


@router.post("/plan/jobs", response_model=PlanJobCreateResponse, status_code=201)
def create_plan_job_endpoint(
    body: PlanJobCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    allowed, message = can_plan_drama(db, user, body.drama_name)
    if not allowed:
        raise HTTPException(status_code=403, detail=message)

    payload = {
        "project_name": body.project_name,
        "steps": body.steps,
        "ordered_files": body.ordered_files,
        "target_clips_count": body.target_clips_count,
        "max_duration_seconds": body.max_duration_seconds,
        "min_duration_seconds": body.min_duration_seconds,
        "split_ab": body.split_ab,
        "global_speed": body.global_speed,
        "plan_mode": body.plan_mode,
    }
    try:
        job = create_plan_job(db, user.id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PlanJobCreateResponse(job_id=job.id)


@router.get("/plan/jobs/{job_id}", response_model=PlanJobStatusOut)
def get_plan_job_status(
    job_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = get_plan_job(db, job_id, user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="策划任务不存在")
    return PlanJobStatusOut(
        job_id=job.id,
        status=job.status,
        progress=job.progress,
        error=user_facing_plan_error(job.error),
        error_detail=job.error or "",
    )


@router.get("/plan/jobs/{job_id}/result", response_model=PlanJobResultOut)
def get_plan_job_result(
    job_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = get_plan_job(db, job_id, user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="策划任务不存在")
    if job.status == "failed":
        raise HTTPException(
            status_code=400, detail=user_facing_plan_error(job.error)
        )
    if job.status != "done" or not job.result:
        raise HTTPException(status_code=409, detail="策划尚未完成")
    return PlanJobResultOut(job_id=job.id, **job.result)


@router.post("/usage", status_code=201)
def report_usage(
    body: UsageReport,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.usage_meta import (
        format_plan_drama_meta,
        normalize_plan_mode,
        parse_drama_name_from_meta,
    )

    meta = body.meta or ""
    plan_mode = normalize_plan_mode(body.plan_mode) or ""
    # 兼容旧客户端：模式写在 meta 后缀「剧名（混合）」里
    if body.event == "plan_drama":
        drama_name = parse_drama_name_from_meta(meta)
        if not plan_mode:
            from app.services.usage_meta import parse_plan_mode_from_meta

            plan_mode = parse_plan_mode_from_meta(meta) or ""
        meta = format_plan_drama_meta(drama_name, plan_mode or None) if drama_name else meta
        activity_meta = drama_name
    else:
        activity_meta = meta

    if body.event in {"plan_drama", "clip_drama", "download_drama"}:
        assert_can_record(db, user, body.event, activity_meta)

    event = UsageEvent(
        user_id=user.id,
        event=body.event,
        success=body.success,
        duration_ms=max(0, body.duration_ms),
        meta=meta,
        plan_mode=plan_mode if body.event == "plan_drama" else "",
        client_version=body.client_version or "",
    )
    db.add(event)
    record_daily_activity(db, user.id, body.event, activity_meta)
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
    elif body.action == "clip":
        allowed, message = can_clip_drama(db, user, body.drama_name)
    else:
        allowed, message = can_download_drama(db, user, body.drama_name)
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
