"""用户机器信息的写入与读取（每用户仅保留最新一条）。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UserMachine


def upsert_machine(db: Session, user_id: int, payload: dict[str, Any]) -> UserMachine:
    row = db.scalar(select(UserMachine).where(UserMachine.user_id == user_id))
    if row is None:
        row = UserMachine(user_id=user_id)
        db.add(row)

    if "machine_id" in payload:
        row.machine_id = str(payload.get("machine_id") or "")[:64]
    if "ip_address" in payload:
        row.ip_address = str(payload.get("ip_address") or "")[:64]
    if "local_ip" in payload:
        row.local_ip = str(payload.get("local_ip") or "")[:128]

    row.os = str(payload.get("os") or "")[:255]
    row.hostname = str(payload.get("hostname") or "")[:128]
    row.cpu_name = str(payload.get("cpu_name") or "")[:255]
    row.cpu_cores_logical = max(0, int(payload.get("cpu_cores_logical") or 0))
    row.cpu_cores_physical = max(0, int(payload.get("cpu_cores_physical") or 0))
    row.ram_total_mb = max(0, int(payload.get("ram_total_mb") or 0))
    row.ram_available_mb = max(0, int(payload.get("ram_available_mb") or 0))

    gpus = payload.get("gpus")
    if not isinstance(gpus, list):
        gpus = []
    row.gpus = json.dumps(gpus[:8], ensure_ascii=False, separators=(",", ":"))
    row.gpu_summary = str(payload.get("gpu_summary") or "")[:512]
    row.client_version = str(payload.get("client_version") or "")[:32]

    db.flush()
    return row


def get_machine(db: Session, user_id: int) -> UserMachine | None:
    return db.scalar(select(UserMachine).where(UserMachine.user_id == user_id))
