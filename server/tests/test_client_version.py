import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.testclient import TestClient

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.config import settings
from app.routers import client as client_router
from app.services import client_version as client_version_service


@pytest.fixture()
def version_client(monkeypatch, tmp_path):
    # 默认无 version.json，走 .env 回退
    empty = tmp_path / "empty_release"
    empty.mkdir()
    monkeypatch.setattr(settings, "client_releases_dir", str(empty))
    monkeypatch.setattr(settings, "client_latest_version", "1.2.0")
    monkeypatch.setattr(settings, "client_min_supported_version", "1.0.0")
    monkeypatch.setattr(settings, "client_download_url", "https://example.com/setup.exe")
    monkeypatch.setattr(settings, "client_changelog", "测试更新说明")
    monkeypatch.setattr(settings, "public_base_url", "")

    app = FastAPI()
    app.include_router(client_router.router)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


def test_get_client_version(version_client):
    resp = version_client.get("/api/client/version")
    assert resp.status_code == 200
    data = resp.json()
    assert data["latest"] == "1.2.0"
    assert data["min_supported"] == "1.0.0"
    assert data["download_url"] == "https://example.com/setup.exe"
    assert data["changelog"] == "测试更新说明"


def test_get_client_version_from_release_dir(monkeypatch, tmp_path):
    installer = tmp_path / "app-v2.exe"
    installer.write_bytes(b"fake-installer")
    version_file = tmp_path / "version.json"
    version_file.write_text(
        json.dumps(
            {
                "latest": "0.0.2",
                "min_supported": "0.0.1",
                "installer": "app-v2.exe",
                "changelog": "目录发版",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "client_releases_dir", str(tmp_path))
    monkeypatch.setattr(settings, "public_base_url", "https://api.example.com")

    app = FastAPI()
    app.include_router(client_router.router)
    app.mount(
        client_version_service.STATIC_MOUNT_PATH,
        StaticFiles(directory=str(tmp_path)),
        name="release",
    )

    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.get("/api/client/version")
        assert resp.status_code == 200
        data = resp.json()
        assert data["latest"] == "0.0.2"
        assert data["min_supported"] == "0.0.1"
        assert data["changelog"] == "目录发版"
        assert data["download_url"] == "https://api.example.com/release/app-v2.exe"

        dl = client.get("/release/app-v2.exe")
        assert dl.status_code == 200
        assert dl.content == b"fake-installer"
