from pathlib import Path

from app.common.config import cfg

CHANGDU_DIR = Path.cwd() / "changdu_data"
AUTH_FILE = CHANGDU_DIR / "auth.json"
# 设备标识 Cookie 的本地快照：站点用它识别"同一台设备"，
# 每次都用全新上下文会让同一 IP 反复出现新设备，反而可疑。
DEVICE_COOKIES_FILE = CHANGDU_DIR / "device_cookies.json"
DEFAULT_DOWNLOAD_FOLDER = "视频下载"
DEFAULT_DOWNLOAD_DIR = Path.home() / "Desktop" / DEFAULT_DOWNLOAD_FOLDER
DONE_FILE = CHANGDU_DIR / "batch_download_done.txt"
LOG_FILE = CHANGDU_DIR / "batch_download_log.json"
PENDING_FILE = CHANGDU_DIR / "batch_download_pending.json"


def ensure_changdu_dirs() -> None:
    CHANGDU_DIR.mkdir(parents=True, exist_ok=True)


def resolve_video_download_root() -> str:
    custom = cfg.video_download_dir.value.strip()
    if custom:
        return custom
    DEFAULT_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return str(DEFAULT_DOWNLOAD_DIR)
