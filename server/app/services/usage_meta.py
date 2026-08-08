"""使用记录 meta：策划剧目名与模式的编码/解析。"""

from __future__ import annotations

PLAN_MODE_LABELS: dict[str, str] = {
    "short": "短片",
    "long": "长片",
    "mixed": "混合",
}

_LABEL_TO_MODE = {v: k for k, v in PLAN_MODE_LABELS.items()}


def normalize_plan_mode(value: str | None) -> str | None:
    mode = str(value or "").strip().lower()
    if mode in PLAN_MODE_LABELS:
        return mode
    return None


def format_plan_drama_meta(drama_name: str, plan_mode: str | None = None) -> str:
    """后台「使用记录」详情：剧名（短片|长片|混合）。"""
    name = (drama_name or "").strip()
    mode = normalize_plan_mode(plan_mode)
    if not name:
        return ""
    if mode is None:
        return name
    return f"{name}（{PLAN_MODE_LABELS[mode]}）"


def parse_drama_name_from_meta(meta: str) -> str:
    """从策划 meta 取出剧名（兼容旧版纯剧名）。"""
    text = (meta or "").strip()
    if not text:
        return ""
    for label in PLAN_MODE_LABELS.values():
        suffix = f"（{label}）"
        if text.endswith(suffix):
            return text[: -len(suffix)].strip()
    if "|mode=" in text:
        return text.split("|mode=", 1)[0].strip()
    return text


def parse_plan_mode_from_meta(meta: str) -> str | None:
    text = (meta or "").strip()
    for label, mode in _LABEL_TO_MODE.items():
        if text.endswith(f"（{label}）"):
            return mode
    if "|mode=" in text:
        return normalize_plan_mode(text.split("|mode=", 1)[1])
    return None
