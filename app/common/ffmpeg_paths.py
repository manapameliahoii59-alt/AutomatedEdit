import builtins
import os
import shutil
import sys
from pathlib import Path

from app.common.config import cfg

_FFMPEG_REL = Path("tools") / "ffmpeg" / "win"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _app_base_dir() -> Path:
    if getattr(builtins, "__compiled__", False):
        return Path(sys.executable).resolve().parent
    return _project_root()


def _bundled_exe(name: str) -> Path:
    return _app_base_dir() / _FFMPEG_REL / f"{name}.exe"


def resolve_ffmpeg() -> str:
    custom = cfg.ffmpeg_path.value
    if custom and os.path.isfile(custom):
        return custom

    bundled = _bundled_exe("ffmpeg")
    if bundled.is_file():
        return str(bundled)

    found = shutil.which("ffmpeg")
    if found:
        return found

    raise FileNotFoundError(
        "未找到 FFmpeg。请重新安装应用，或在设置中指定 ffmpeg.exe 路径。"
    )


def resolve_ffprobe() -> str:
    custom = cfg.ffprobe_path.value
    if custom and os.path.isfile(custom):
        return custom

    bundled = _bundled_exe("ffprobe")
    if bundled.is_file():
        return str(bundled)

    found = shutil.which("ffprobe")
    if found:
        return found

    raise FileNotFoundError(
        "未找到 FFprobe。请重新安装应用，或在设置中指定 ffprobe.exe 路径。"
    )


def effective_ffmpeg_display() -> str:
    try:
        return resolve_ffmpeg()
    except FileNotFoundError:
        return cfg.ffmpeg_path.value or "未找到（使用内置或系统 PATH）"


def effective_ffprobe_display() -> str:
    try:
        return resolve_ffprobe()
    except FileNotFoundError:
        return cfg.ffprobe_path.value or "未找到（使用内置或系统 PATH）"
