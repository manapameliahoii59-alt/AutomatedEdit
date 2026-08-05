"""策划条数 / 时长范围：短片与长片两套参数。"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

# 与服务端 plan_director 默认一致
DEFAULT_CLIP_COUNT = 15
MIN_CLIP_COUNT = 5
MAX_CLIP_COUNT = 15

PLAN_MODE_SHORT = "short"
PLAN_MODE_LONG = "long"
PlanMode = Literal["short", "long"]

# 长片：最短固定 2.5 分钟；最长 5~15 分钟
MIN_DURATION_SECONDS = 150  # 2.5 分钟，固定最短
DEFAULT_MAX_DURATION_SECONDS = 720  # 默认最长 12 分钟
MIN_MAX_DURATION_SECONDS = 300  # 「最长时长」最低可选 5 分钟
MAX_MAX_DURATION_SECONDS = 900  # 最高 15 分钟

# 短片：最短固定 2 分钟；最长 2~5 分钟
SHORT_MIN_DURATION_SECONDS = 120
DEFAULT_SHORT_MAX_DURATION_SECONDS = 300
MIN_SHORT_MAX_DURATION_SECONDS = 120
MAX_SHORT_MAX_DURATION_SECONDS = 300

# 默认 A:B = 6:9（仅长片）
_DEFAULT_A = 6
_DEFAULT_TOTAL = 15


class ActivePlanParams(TypedDict):
    mode: PlanMode
    clip_count: int
    min_duration_sec: int
    max_duration_sec: int
    split_ab: bool


def clamp_clip_count(value: int | float | str | None) -> int:
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = DEFAULT_CLIP_COUNT
    return max(MIN_CLIP_COUNT, min(MAX_CLIP_COUNT, n))


def clamp_plan_mode(value: Any) -> PlanMode:
    if str(value or "").strip().lower() == PLAN_MODE_SHORT:
        return PLAN_MODE_SHORT
    return PLAN_MODE_LONG


def clamp_max_duration_seconds(value: int | float | str | None) -> int:
    """长片最长时长 clamp（300~900）。"""
    try:
        n = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = DEFAULT_MAX_DURATION_SECONDS
    return max(MIN_MAX_DURATION_SECONDS, min(MAX_MAX_DURATION_SECONDS, n))


def clamp_short_max_duration_seconds(value: int | float | str | None) -> int:
    """短片最长时长 clamp（120~300）。"""
    try:
        n = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = DEFAULT_SHORT_MAX_DURATION_SECONDS
    return max(MIN_SHORT_MAX_DURATION_SECONDS, min(MAX_SHORT_MAX_DURATION_SECONDS, n))


def split_ab_counts(total: int) -> tuple[int, int]:
    """按默认 6:9 比例分配 A/B；保证两边至少各 1（总条数≥2 时）。"""
    total = clamp_clip_count(total)
    if total <= 1:
        return total, 0
    a = int(round(total * _DEFAULT_A / _DEFAULT_TOTAL))
    a = min(max(a, 1), total - 1)
    return a, total - a


def max_duration_minutes_from_seconds(seconds: int) -> int:
    """长片 UI 用整分钟；最长时长 5~15 分钟。"""
    sec = clamp_max_duration_seconds(seconds)
    mins = int(round(sec / 60.0))
    return max(5, min(15, mins))


def max_duration_seconds_from_minutes(minutes: int | float) -> int:
    try:
        m = int(minutes)
    except (TypeError, ValueError):
        m = 12
    m = max(5, min(15, m))
    return clamp_max_duration_seconds(m * 60)


def short_max_duration_minutes_from_seconds(seconds: int) -> int:
    """短片 UI 用整分钟；最长时长 2~5 分钟。"""
    sec = clamp_short_max_duration_seconds(seconds)
    mins = int(round(sec / 60.0))
    return max(2, min(5, mins))


def short_max_duration_seconds_from_minutes(minutes: int | float) -> int:
    try:
        m = int(minutes)
    except (TypeError, ValueError):
        m = 5
    m = max(2, min(5, m))
    return clamp_short_max_duration_seconds(m * 60)


def resolve_active_plan_params() -> ActivePlanParams:
    """按当前 cfg.plan_mode 解析策划请求参数。"""
    from app.common.config import cfg

    mode = clamp_plan_mode(cfg.plan_mode.value)
    if mode == PLAN_MODE_SHORT:
        return {
            "mode": PLAN_MODE_SHORT,
            "clip_count": clamp_clip_count(cfg.plan_short_clip_count.value),
            "min_duration_sec": SHORT_MIN_DURATION_SECONDS,
            "max_duration_sec": clamp_short_max_duration_seconds(
                cfg.plan_short_max_duration_sec.value
            ),
            "split_ab": False,
        }
    return {
        "mode": PLAN_MODE_LONG,
        "clip_count": clamp_clip_count(cfg.plan_clip_count.value),
        "min_duration_sec": MIN_DURATION_SECONDS,
        "max_duration_sec": clamp_max_duration_seconds(cfg.plan_max_duration_sec.value),
        "split_ab": True,
    }


def apply_plan_settings_dict(data: dict | None) -> None:
    """把服务端 plan 命名空间写入本地 cfg（供下次策划请求使用）。"""
    if not data:
        return
    from qfluentwidgets import qconfig

    from app.common.config import cfg

    if data.get("mode") is not None:
        qconfig.set(cfg.plan_mode, clamp_plan_mode(data["mode"]))
    if data.get("clip_count") is not None:
        qconfig.set(cfg.plan_clip_count, clamp_clip_count(data["clip_count"]))
    if data.get("max_duration_sec") is not None:
        qconfig.set(
            cfg.plan_max_duration_sec,
            clamp_max_duration_seconds(data["max_duration_sec"]),
        )
    if data.get("short_clip_count") is not None:
        qconfig.set(
            cfg.plan_short_clip_count, clamp_clip_count(data["short_clip_count"])
        )
    if data.get("short_max_duration_sec") is not None:
        qconfig.set(
            cfg.plan_short_max_duration_sec,
            clamp_short_max_duration_seconds(data["short_max_duration_sec"]),
        )


def plan_settings_patch(
    *,
    mode: PlanMode | str | None = None,
    clip_count: int | None = None,
    max_duration_sec: int | None = None,
    short_clip_count: int | None = None,
    short_max_duration_sec: int | None = None,
) -> dict:
    plan: dict[str, Any] = {}
    if mode is not None:
        plan["mode"] = clamp_plan_mode(mode)
    if clip_count is not None:
        plan["clip_count"] = clamp_clip_count(clip_count)
    if max_duration_sec is not None:
        plan["max_duration_sec"] = clamp_max_duration_seconds(max_duration_sec)
    if short_clip_count is not None:
        plan["short_clip_count"] = clamp_clip_count(short_clip_count)
    if short_max_duration_sec is not None:
        plan["short_max_duration_sec"] = clamp_short_max_duration_seconds(
            short_max_duration_sec
        )
    return {"plan": plan}
