from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from fastapi import Request

from app.config import settings
from app.schemas import ClientVersionOut

SERVER_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = SERVER_ROOT.parent
STATIC_MOUNT_PATH = "/release"


def resolve_releases_dir() -> Path:
    """解析安装包目录：优先 .env，其次仓库根 release/，再次 server/release。"""
    configured = (settings.client_releases_dir or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()

    candidates = (REPO_ROOT / "release", SERVER_ROOT / "release")
    for path in candidates:
        if (path / "version.json").is_file():
            return path.resolve()
    for path in candidates:
        if path.is_dir():
            return path.resolve()
    return (SERVER_ROOT / "release").resolve()


def get_releases_dir() -> Path:
    return resolve_releases_dir()


def get_version_file() -> Path:
    return get_releases_dir() / "version.json"


def _load_version_file() -> dict | None:
    version_file = get_version_file()
    if not version_file.is_file():
        return None
    try:
        data = json.loads(version_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _public_base_url(request: Request | None) -> str:
    configured = (settings.public_base_url or "").strip().rstrip("/")
    if configured:
        return configured
    if request is not None:
        return str(request.base_url).rstrip("/")
    return ""


def _build_download_url(
    *,
    request: Request | None,
    installer: str,
    explicit_url: str = "",
) -> str:
    explicit = (explicit_url or "").strip()
    if explicit:
        return explicit

    name = (installer or "").strip()
    if not name:
        return ""

    base = _public_base_url(request)
    encoded = quote(name)
    path = f"{STATIC_MOUNT_PATH}/{encoded}"
    if base:
        return f"{base}{path}"
    return path


def build_client_version_out(request: Request | None = None) -> ClientVersionOut:
    """优先读 release/version.json；没有则回退到 .env 的 CLIENT_*。"""
    file_data = _load_version_file()
    if file_data is not None:
        latest = str(file_data.get("latest") or "").strip()
        min_supported = (
            str(file_data.get("min_supported") or "").strip() or latest
        )
        changelog = str(file_data.get("changelog") or "").strip()
        installer = str(
            file_data.get("installer") or file_data.get("filename") or ""
        ).strip()
        download_url = _build_download_url(
            request=request,
            installer=installer,
            explicit_url=str(file_data.get("download_url") or ""),
        )
        return ClientVersionOut(
            latest=latest,
            min_supported=min_supported,
            download_url=download_url,
            changelog=changelog,
        )

    latest = (settings.client_latest_version or "").strip()
    min_supported = (settings.client_min_supported_version or "").strip() or latest
    download_url = (settings.client_download_url or "").strip()
    changelog = (settings.client_changelog or "").strip()
    return ClientVersionOut(
        latest=latest,
        min_supported=min_supported,
        download_url=download_url,
        changelog=changelog,
    )


# 兼容旧测试/导入名
RELEASES_DIR = SERVER_ROOT / "release"
VERSION_FILE = RELEASES_DIR / "version.json"
