import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.config import settings
from app.routers import client as client_router


@pytest.fixture()
def version_client(monkeypatch):
    monkeypatch.setattr(settings, "client_latest_version", "1.2.0")
    monkeypatch.setattr(settings, "client_min_supported_version", "1.0.0")
    monkeypatch.setattr(settings, "client_download_url", "https://example.com/setup.exe")
    monkeypatch.setattr(settings, "client_changelog", "测试更新说明")

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
