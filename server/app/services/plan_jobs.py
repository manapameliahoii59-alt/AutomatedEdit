"""策划异步任务（MySQL 持久化，按用户隔离）。"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import PlanJob
from app.services.plan_crypto import encrypt_plan_payload
from app.services.plan_director import run_plan
from app.services.plan_secrets import ensure_user_secret, resolve_deepseek_keys

logger = logging.getLogger(__name__)

JOB_TTL = timedelta(hours=2)
# 进度回调写库节流，避免 LLM 流式回调打爆连接池
_PROGRESS_WRITE_INTERVAL_SEC = 1.0


@dataclass
class PlanJobRecord:
    id: str
    user_id: int
    status: str = "pending"
    progress: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    result: dict[str, str] | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _loads_dict(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _row_to_record(row: PlanJob) -> PlanJobRecord:
    result = _loads_dict(row.result_json or "")
    return PlanJobRecord(
        id=row.id,
        user_id=row.user_id,
        status=row.status,
        progress=_loads_dict(row.progress_json or ""),
        error=row.error or "",
        result=result or None,
        created_at=row.created_at or _utc_now(),
        updated_at=row.updated_at or _utc_now(),
    )


def _cleanup_old_jobs() -> None:
    cutoff = _utc_now() - JOB_TTL
    db = SessionLocal()
    try:
        db.execute(delete(PlanJob).where(PlanJob.updated_at < cutoff))
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("清理过期策划任务失败")
    finally:
        db.close()


def fail_interrupted_jobs() -> int:
    """进程启动时：将未完成任务标为失败，避免客户端无限轮询僵尸任务。"""
    db = SessionLocal()
    try:
        rows = db.scalars(
            select(PlanJob).where(PlanJob.status.in_(("pending", "running")))
        ).all()
        for row in rows:
            row.status = "failed"
            row.error = "服务重启，策划任务已中断，请重新策划"
            row.updated_at = _utc_now()
        db.commit()
        return len(rows)
    except Exception:
        db.rollback()
        logger.exception("标记中断策划任务失败")
        return 0
    finally:
        db.close()


def _persist_job(
    job_id: str,
    *,
    status: str | None = None,
    progress: dict[str, Any] | None = None,
    error: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    db = SessionLocal()
    try:
        row = db.get(PlanJob, job_id)
        if row is None:
            return
        if status is not None:
            row.status = status
        if progress is not None:
            row.progress_json = json.dumps(progress, ensure_ascii=False)
        if error is not None:
            row.error = error
        if result is not None:
            row.result_json = json.dumps(result, ensure_ascii=False)
        row.updated_at = _utc_now()
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("更新策划任务失败 job_id=%s", job_id)
    finally:
        db.close()


def _run_job(job_id: str, payload: dict[str, Any], plan_key: str, api_keys_raw: str) -> None:
    _persist_job(job_id, status="running")
    last_progress_at = 0.0

    def on_progress(progress: dict[str, Any]) -> None:
        nonlocal last_progress_at
        now = time.monotonic()
        if now - last_progress_at < _PROGRESS_WRITE_INTERVAL_SEC:
            return
        last_progress_at = now
        _persist_job(job_id, progress=progress)

    try:
        plans = run_plan(
            project_name=payload["project_name"],
            steps=payload["steps"],
            ordered_files=payload["ordered_files"],
            api_keys_raw=api_keys_raw,
            api_url=settings.deepseek_api_url,
            model_name=settings.deepseek_model,
            progress_callback=on_progress,
            target_clips_count=payload.get("target_clips_count"),
            max_duration_seconds=payload.get("max_duration_seconds"),
            min_duration_seconds=payload.get("min_duration_seconds"),
            split_ab=payload.get("split_ab"),
            global_speed=payload.get("global_speed"),
            plan_mode=payload.get("plan_mode"),
        )
        from app.services.plan_director import clamp_clip_count

        target_total = clamp_clip_count(payload.get("target_clips_count") or 15)
        underfilled = len(plans) < target_total
        encrypted = encrypt_plan_payload(plan_key, plans)
        detail = "完成"
        if underfilled:
            detail = (
                f"仅通过 {len(plans)}/{target_total} 条"
                "（多数候选因时长或台词未匹配被过滤）"
            )
        plan_mode = str(payload.get("plan_mode") or "").strip().lower()
        _persist_job(
            job_id,
            status="done",
            result=encrypted,
            progress={
                "phase": "plan",
                "current": len(plans),
                "total": target_total,
                "detail": detail,
                "underfilled": underfilled,
                "project_name": str(payload.get("project_name") or ""),
                "plan_mode": plan_mode,
            },
            error="",
        )
    except Exception as exc:
        _persist_job(job_id, status="failed", error=str(exc))


def create_plan_job(db: Session, user_id: int, payload: dict[str, Any]) -> PlanJobRecord:
    _cleanup_old_jobs()
    ensure_user_secret(db, user_id)
    api_keys_raw = resolve_deepseek_keys(db, user_id)
    if not api_keys_raw:
        raise ValueError("未配置策划服务密钥，请联系管理员")

    row_secret = ensure_user_secret(db, user_id)
    plan_key = row_secret.plan_decrypt_key
    job_id = uuid.uuid4().hex
    from app.services.plan_director import clamp_clip_count

    target_total = clamp_clip_count(payload.get("target_clips_count") or 15)
    project_name = str(payload.get("project_name") or "").strip()
    plan_mode = str(payload.get("plan_mode") or "").strip().lower()
    if plan_mode not in {"short", "long", "mixed"}:
        # 兼容旧客户端：无 mode 时由 split_ab 推断
        split_ab = payload.get("split_ab")
        use_ab = True if split_ab is None else bool(split_ab)
        plan_mode = "short" if not use_ab else "long"
    progress = {
        "phase": "plan",
        "current": 0,
        "total": target_total,
        "detail": "排队中…",
        "project_name": project_name,
        "plan_mode": plan_mode,
    }
    now = _utc_now()
    row = PlanJob(
        id=job_id,
        user_id=user_id,
        status="pending",
        project_name=project_name,
        plan_mode=plan_mode,
        progress_json=json.dumps(progress, ensure_ascii=False),
        error="",
        result_json="",
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    thread = threading.Thread(
        target=_run_job,
        args=(job_id, payload, plan_key, api_keys_raw),
        daemon=True,
        name=f"plan-job-{job_id[:8]}",
    )
    thread.start()
    return _row_to_record(row)


def get_plan_job(db: Session, job_id: str, user_id: int) -> PlanJobRecord | None:
    row = db.scalar(
        select(PlanJob).where(PlanJob.id == job_id, PlanJob.user_id == user_id)
    )
    if row is None:
        return None
    return _row_to_record(row)
