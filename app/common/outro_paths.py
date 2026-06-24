import builtins
import sys
from pathlib import Path

_OUTRO_REL = Path("tools") / "outro"

HORIZONTAL_OUTRO = "横屏结尾.mp4"
VERTICAL_OUTRO = "竖屏结尾.mp4"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _app_base_dir() -> Path:
    if getattr(builtins, "__compiled__", False):
        return Path(sys.executable).resolve().parent
    return _project_root()


def resolve_outro_path(horizontal: bool) -> str | None:
    filename = HORIZONTAL_OUTRO if horizontal else VERTICAL_OUTRO
    bundled = _app_base_dir() / _OUTRO_REL / filename
    if bundled.is_file():
        return str(bundled)
    legacy = _project_root() / filename
    if legacy.is_file():
        return str(legacy)
    return None


def outro_filename(horizontal: bool) -> str:
    return HORIZONTAL_OUTRO if horizontal else VERTICAL_OUTRO
