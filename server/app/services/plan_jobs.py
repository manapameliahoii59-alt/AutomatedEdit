"""策划异步任务（内存队列，按用户隔离）。"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.services.plan_crypto import encrypt_plan_payload
from app.services.plan_director import run_plan
from app.services.plan_secrets import ensure_user_secret, resolve_deepseek_keys


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


_lock = threading.Lock()
_jobs: dict[str, PlanJobRecord] = {}
JOB_TTL = timedelta(hours=2)


def _cleanup_old_jobs() -> None:
    cutoff = datetime.now(timezone.utc) - JOB_TTL
    stale = [job_id for job_id, job in _jobs.items() if job.updated_at < cutoff]
    for job_id in stale:
        _jobs.pop(job_id, None)


def _set_progress(job: PlanJobRecord, progress: dict[str, Any]) -> None:
    job.progress = progress
    job.updated_at = datetime.now(timezone.utc)


def _run_job(job_id: str, payload: dict[str, Any], plan_key: str, api_keys_raw: str) -> None:
    job = _jobs.get(job_id)
    if job is None:
        return
    job.status = "running"
    job.updated_at = datetime.now(timezone.utc)

    try:
        plans = run_plan(
            project_name=payload["project_name"],
            steps=payload["steps"],
            ordered_files=payload["ordered_files"],
            api_keys_raw=api_keys_raw,
            api_url=settings.deepseek_api_url,
            model_name=settings.deepseek_model,
            progress_callback=lambda p: _set_progress(job, p),
        )
        encrypted = encrypt_plan_payload(plan_key, plans)
        job.result = encrypted
        job.status = "done"
        job.progress = {
            "phase": "plan",
            "current": len(plans),
            "total": len(plans),
            "detail": "完成",
        }
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
    finally:
        job.updated_at = datetime.now(timezone.utc)


def create_plan_job(db: Session, user_id: int, payload: dict[str, Any]) -> PlanJobRecord:
    _cleanup_old_jobs()
    row = ensure_user_secret(db, user_id)
    plan_key = row.plan_decrypt_key
    api_keys_raw = resolve_deepseek_keys(db, user_id)
    if not api_keys_raw:
        raise ValueError("未配置策划服务密钥，请联系管理员")

    job_id = uuid.uuid4().hex
    job = PlanJobRecord(
        id=job_id,
        user_id=user_id,
        progress={"phase": "plan", "current": 0, "total": 15, "detail": "排队中…"},
    )
    with _lock:
        _jobs[job_id] = job

    thread = threading.Thread(
        target=_run_job,
        args=(job_id, payload, plan_key, api_keys_raw),
        daemon=True,
        name=f"plan-job-{job_id[:8]}",
    )
    thread.start()
    return job


def get_plan_job(job_id: str, user_id: int) -> PlanJobRecord | None:
    job = _jobs.get(job_id)
    if job is None or job.user_id != user_id:
        return None
    return job
