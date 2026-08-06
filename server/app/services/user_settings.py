"""用户客户端配置的读取、合并与校验。"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UserSettings
from app.schemas import ClipEditSettings, PlanSettings, UserSettingsOut, VideoDownloadSettings

_KNOWN_NAMESPACES = frozenset({"video_download", "plan", "clip_edit"})


def _load_data(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _dump_data(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in patch.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _validate_namespaces(data: dict[str, Any]) -> dict[str, Any]:
    if "video_download" in data:
        validated = VideoDownloadSettings.model_validate(data["video_download"])
        data["video_download"] = validated.model_dump()
    if "plan" in data:
        validated = PlanSettings.model_validate(data["plan"])
        data["plan"] = validated.model_dump()
    if "clip_edit" in data:
        raw_clip = data["clip_edit"] if isinstance(data["clip_edit"], dict) else {}
        validated = ClipEditSettings.model_validate(raw_clip)
        dumped = validated.model_dump(exclude_none=True)
        # 未显式写入过的叠字不要用默认值落库，否则 GET 会一直像「已配置默认」
        if "overlay_title" not in raw_clip:
            dumped.pop("overlay_title", None)
        if "overlay_disclaimer" not in raw_clip:
            dumped.pop("overlay_disclaimer", None)
        if "overlay_text_library" not in raw_clip:
            dumped.pop("overlay_text_library", None)
        data["clip_edit"] = dumped
    return data


def _patch_to_dict(patch: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in patch.items():
        if value is None:
            continue
        if isinstance(value, dict):
            nested = {k: v for k, v in value.items() if v is not None}
            if nested:
                cleaned[key] = nested
        else:
            cleaned[key] = value
    return cleaned


def _get_or_create_row(db: Session, user_id: int) -> UserSettings:
    row = db.scalar(select(UserSettings).where(UserSettings.user_id == user_id))
    if row is not None:
        return row
    row = UserSettings(user_id=user_id, data="{}")
    db.add(row)
    db.flush()
    return row


def get_user_settings(db: Session, user_id: int) -> UserSettingsOut:
    row = db.scalar(select(UserSettings).where(UserSettings.user_id == user_id))
    data = _load_data(row.data if row is not None else "")
    return build_settings_out(data, row.updated_at if row is not None else None)


def build_settings_out(data: dict[str, Any], updated_at) -> UserSettingsOut:
    payload: dict[str, Any] = {"updated_at": updated_at}
    vd = data.get("video_download", {})
    payload["video_download"] = VideoDownloadSettings.model_validate(vd)
    plan = data.get("plan", {})
    payload["plan"] = PlanSettings.model_validate(plan)
    clip_edit = data.get("clip_edit", {})
    payload["clip_edit"] = ClipEditSettings.model_validate(clip_edit)
    for key, value in data.items():
        if key not in _KNOWN_NAMESPACES:
            payload[key] = value
    return UserSettingsOut.model_validate(payload)


def patch_user_settings(db: Session, user_id: int, patch: dict[str, Any]) -> UserSettingsOut:
    row = _get_or_create_row(db, user_id)
    current = _load_data(row.data)
    merged = _deep_merge(current, _patch_to_dict(patch))
    merged = _validate_namespaces(merged)
    row.data = _dump_data(merged)
    db.flush()
    db.refresh(row)
    return build_settings_out(merged, row.updated_at)
