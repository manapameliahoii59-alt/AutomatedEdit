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


def parse_version(version: str) -> tuple[int, ...]:
    text = (version or "").strip()
    if not text:
        return (0,)
    parts: list[int] = []
    for segment in text.split("."):
        token = segment.split("-", 1)[0].strip()
        if not token:
            parts.append(0)
            continue
        digits = ""
        for ch in token:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits or "0"))
    return tuple(parts) if parts else (0,)


def compare_versions(left: str, right: str) -> int:
    """left < right 返回 -1，相等 0，left > right 返回 1。"""
    a = parse_version(left)
    b = parse_version(right)
    width = max(len(a), len(b))
    a = a + (0,) * (width - len(a))
    b = b + (0,) * (width - len(b))
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def is_version_older(current: str, target: str) -> bool:
    return compare_versions(current, target) < 0


def save_version_file(
    *,
    latest: str,
    min_supported: str,
    download_url: str = "",
    changelog: str = "",
    installer: str = "",
) -> dict:
    version_file = get_version_file()
    version_file.parent.mkdir(parents=True, exist_ok=True)

    existing = _load_version_file() or {}
    data = {
        **existing,
        "latest": (latest or "").strip(),
        "min_supported": (min_supported or "").strip() or (latest or "").strip(),
        "download_url": (download_url or "").strip(),
        "changelog": (changelog or "").strip(),
    }
    if installer.strip():
        data["installer"] = installer.strip()
    elif "installer" in data and not data["installer"]:
        del data["installer"]

    version_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def assert_client_version_supported(
    client_version: str | None,
    *,
    request: Request | None = None,
) -> None:
    if not client_version or not client_version.strip():
        return

    version_info = build_client_version_out(request)
    min_supported = (version_info.min_supported or "").strip()
    if not min_supported:
        return

    cur_ver = client_version.strip().lstrip("vV")
    min_ver = min_supported.lstrip("vV")
    if is_version_older(cur_ver, min_ver):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=426,
            detail=f"当前客户端版本 (v{cur_ver}) 已停用，最低要求版本为 v{min_ver}，请升级后继续使用！",
        )


# 兼容旧测试/导入名
RELEASES_DIR = SERVER_ROOT / "release"
VERSION_FILE = RELEASES_DIR / "version.json"

