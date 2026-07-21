"""策划条数 / 时长范围：默认与 A/B 组比例分配。"""

from __future__ import annotations

# 与服务端 plan_director 默认一致
DEFAULT_CLIP_COUNT = 15
MIN_CLIP_COUNT = 5
MAX_CLIP_COUNT = 15

MIN_DURATION_SECONDS = 150  # 2.5 分钟，固定最短
DEFAULT_MAX_DURATION_SECONDS = 720  # 默认最长 12 分钟
MIN_MAX_DURATION_SECONDS = 300  # 「最长时长」最低可选 5 分钟
MAX_MAX_DURATION_SECONDS = 900  # 最高 15 分钟

# 默认 A:B = 6:9
_DEFAULT_A = 6
_DEFAULT_TOTAL = 15


def clamp_clip_count(value: int | float | str | None) -> int:
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = DEFAULT_CLIP_COUNT
    return max(MIN_CLIP_COUNT, min(MAX_CLIP_COUNT, n))


def clamp_max_duration_seconds(value: int | float | str | None) -> int:
    try:
        n = int(round(float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        n = DEFAULT_MAX_DURATION_SECONDS
    return max(MIN_MAX_DURATION_SECONDS, min(MAX_MAX_DURATION_SECONDS, n))


def split_ab_counts(total: int) -> tuple[int, int]:
    """按默认 6:9 比例分配 A/B；保证两边至少各 1（总条数≥2 时）。"""
    total = clamp_clip_count(total)
    if total <= 1:
        return total, 0
    a = int(round(total * _DEFAULT_A / _DEFAULT_TOTAL))
    a = min(max(a, 1), total - 1)
    return a, total - a


def max_duration_minutes_from_seconds(seconds: int) -> int:
    """UI 用整分钟；最长时长 5~15 分钟。"""
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


def apply_plan_settings_dict(data: dict | None) -> None:
    """把服务端 plan 命名空间写入本地 cfg（供下次策划请求使用）。"""
    if not data:
        return
    from qfluentwidgets import qconfig

    from app.common.config import cfg

    if data.get("clip_count") is not None:
        qconfig.set(cfg.plan_clip_count, clamp_clip_count(data["clip_count"]))
    if data.get("max_duration_sec") is not None:
        qconfig.set(
            cfg.plan_max_duration_sec,
            clamp_max_duration_seconds(data["max_duration_sec"]),
        )


def plan_settings_patch(clip_count: int, max_duration_sec: int) -> dict:
    return {
        "plan": {
            "clip_count": clamp_clip_count(clip_count),
            "max_duration_sec": clamp_max_duration_seconds(max_duration_sec),
        }
    }
