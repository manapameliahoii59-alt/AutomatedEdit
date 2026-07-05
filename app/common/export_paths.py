import datetime
import os
import re
from pathlib import Path

from app.common.config import cfg

DEFAULT_EXPORT_FOLDER = "剪辑输出"


def resolve_clip_export_root() -> str:
    custom = cfg.clip_export_dir.value.strip()
    if custom:
        return custom
    return str(Path.home() / "Desktop" / DEFAULT_EXPORT_FOLDER)


def resolve_project_export_dir(project_name: str) -> str:
    root = resolve_clip_export_root()
    safe_name = _sanitize_dir_name(project_name)
    path = os.path.join(root, safe_name)
    os.makedirs(path, exist_ok=True)
    return path


def _sanitize_name_part(name: str, *, fallback: str = "未命名") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", name.strip())
    return cleaned or fallback


def _sanitize_dir_name(name: str) -> str:
    return _sanitize_name_part(name, fallback="未命名剧目")


def build_clip_export_filename(
    project_name: str,
    sequence: int,
    *,
    when: datetime.datetime | None = None,
    tag: str | None = None,
) -> str:
    """生成导出视频文件名（不含扩展名）：剧名-标识-日期-序号。"""
    date_str = (when or datetime.datetime.now()).strftime("%m%d")
    parts = [_sanitize_name_part(project_name, fallback="未命名剧目")]
    tag = cfg.clip_export_name_tag.value.strip() if tag is None else tag.strip()
    if tag:
        safe_tag = _sanitize_name_part(tag, fallback="")
        if safe_tag:
            parts.append(safe_tag)
    parts.append(date_str)
    parts.append(f"{sequence:02d}")
    return "-".join(parts)
