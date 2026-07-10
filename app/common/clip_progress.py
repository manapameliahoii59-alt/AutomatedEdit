"""自动化剪辑策划/渲染进度文案格式化。"""

from __future__ import annotations

from typing import Any

TARGET_CLIPS_COUNT = 15


def format_plan_progress(info: dict[str, Any]) -> str:
    current = int(info.get("current") or 0)
    total = int(info.get("total") or TARGET_CLIPS_COUNT)
    return f"策划中 {current}/{total} 条"


def format_render_progress(info: dict[str, Any]) -> str:
    phase = str(info.get("phase") or "render")
    current = int(info.get("current") or 0)
    total = int(info.get("total") or 0)
    if phase == "cache":
        return f"预处理 {current}/{total} 集"
    return f"渲染中 {current}/{total} 条"
