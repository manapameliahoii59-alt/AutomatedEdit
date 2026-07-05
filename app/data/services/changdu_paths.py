from pathlib import Path

from app.common.config import cfg

CHANGDU_DIR = Path.cwd() / "changdu_data"
AUTH_FILE = CHANGDU_DIR / "auth.json"
DEFAULT_DOWNLOAD_DIR = CHANGDU_DIR / "downloads"
DONE_FILE = CHANGDU_DIR / "batch_download_done.txt"
LOG_FILE = CHANGDU_DIR / "batch_download_log.json"
PENDING_FILE = CHANGDU_DIR / "batch_download_pending.json"


def ensure_changdu_dirs() -> None:
    CHANGDU_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def resolve_video_download_root() -> str:
    custom = cfg.video_download_dir.value.strip()
    if custom:
        return custom
    ensure_changdu_dirs()
    return str(DEFAULT_DOWNLOAD_DIR)
