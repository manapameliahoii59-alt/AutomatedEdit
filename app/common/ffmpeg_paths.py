import builtins
import os
import shutil
import sys
from pathlib import Path

_FFMPEG_REL = Path("tools") / "ffmpeg" / "win"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _app_base_dir() -> Path:
    if getattr(builtins, "__compiled__", False):
        return Path(sys.executable).resolve().parent
    return _project_root()


def _bundled_exe(name: str) -> Path:
    return _app_base_dir() / _FFMPEG_REL / f"{name}.exe"


def ensure_bundled_ffmpeg_on_path() -> str | None:
    """仅用内置 ffmpeg 目录改 PATH，不 import config/Qt（可在 import torch 之前调用）。"""
    bundled = _bundled_exe("ffmpeg")
    if not bundled.is_file():
        return None
    ff_dir = str(bundled.resolve().parent)
    path = os.environ.get("PATH", "")
    parts = path.split(os.pathsep) if path else []
    if parts and os.path.normcase(parts[0]) == os.path.normcase(ff_dir):
        return ff_dir
    rest = [
        p for p in parts
        if p and os.path.normcase(p) != os.path.normcase(ff_dir)
    ]
    os.environ["PATH"] = os.pathsep.join([ff_dir, *rest])
    return ff_dir


def resolve_ffmpeg() -> str:
    from app.common.config import cfg

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
    from app.common.config import cfg

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


def ensure_ffmpeg_on_path() -> str | None:
    """将可用 ffmpeg 目录加入 PATH（含用户自定义路径）。可在 torch/Qt 就绪后调用。"""
    try:
        ffmpeg = resolve_ffmpeg()
    except FileNotFoundError:
        return ensure_bundled_ffmpeg_on_path()
    ff_dir = str(Path(ffmpeg).resolve().parent)
    path = os.environ.get("PATH", "")
    parts = path.split(os.pathsep) if path else []
    if parts and os.path.normcase(parts[0]) == os.path.normcase(ff_dir):
        return ff_dir
    rest = [
        p for p in parts
        if p and os.path.normcase(p) != os.path.normcase(ff_dir)
    ]
    os.environ["PATH"] = os.pathsep.join([ff_dir, *rest])
    return ff_dir


def effective_ffmpeg_display() -> str:
    from app.common.config import cfg

    try:
        return resolve_ffmpeg()
    except FileNotFoundError:
        return cfg.ffmpeg_path.value or "未找到（使用内置或系统 PATH）"


def effective_ffprobe_display() -> str:
    from app.common.config import cfg

    try:
        return resolve_ffprobe()
    except FileNotFoundError:
        return cfg.ffprobe_path.value or "未找到（使用内置或系统 PATH）"
