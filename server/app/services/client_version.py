from app.config import settings
from app.schemas import ClientVersionOut


def build_client_version_out() -> ClientVersionOut:
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
