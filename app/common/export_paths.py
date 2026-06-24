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


def _sanitize_dir_name(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", name.strip())
    return cleaned or "未命名剧目"
