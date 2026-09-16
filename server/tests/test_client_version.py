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


def test_version_compare_logic():
    assert client_version_service.compare_versions("0.0.17", "0.0.18") == -1
    assert client_version_service.compare_versions("0.0.18", "0.0.18") == 0
    assert client_version_service.compare_versions("0.0.19", "0.0.18") == 1
    assert client_version_service.compare_versions("1.0", "1.0.0") == 0
    assert client_version_service.is_version_older("0.0.16", "0.0.17") is True
    assert client_version_service.is_version_older("0.0.17", "0.0.17") is False
    assert client_version_service.is_version_older("0.0.18", "0.0.17") is False


def test_assert_client_version_supported(monkeypatch, tmp_path):
    from fastapi import HTTPException

    monkeypatch.setattr(settings, "client_releases_dir", str(tmp_path))
    monkeypatch.setattr(settings, "client_latest_version", "1.0.0")
    monkeypatch.setattr(settings, "client_min_supported_version", "1.0.0")

    # 当无版本 header 时放行
    client_version_service.assert_client_version_supported(None)
    client_version_service.assert_client_version_supported("")

    # 当版本满足时放行
    client_version_service.assert_client_version_supported("1.0.0")
    client_version_service.assert_client_version_supported("1.0.1")
    client_version_service.assert_client_version_supported("v1.0.0")

    # 当版本过低时抛出 426
    with pytest.raises(HTTPException) as exc_info:
        client_version_service.assert_client_version_supported("0.9.9")
    assert exc_info.value.status_code == 426
    assert "已停用" in exc_info.value.detail


def test_save_version_file(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "client_releases_dir", str(tmp_path))
    saved = client_version_service.save_version_file(
        latest="2.0.0",
        min_supported="1.9.0",
        download_url="https://example.com/2.0.0.exe",
        changelog="重大版本发布",
        installer="installer-2.0.0.exe",
    )
    assert saved["latest"] == "2.0.0"
    assert saved["min_supported"] == "1.9.0"

    # 重新加载检查
    v_out = client_version_service.build_client_version_out()
    assert v_out.latest == "2.0.0"
    assert v_out.min_supported == "1.9.0"
    assert v_out.download_url == "https://example.com/2.0.0.exe"
    assert v_out.changelog == "重大版本发布"


def test_login_enforces_version(monkeypatch, tmp_path):
    from app.routers import auth as auth_router

    monkeypatch.setattr(settings, "client_releases_dir", str(tmp_path))
    monkeypatch.setattr(settings, "client_latest_version", "2.0.0")
    monkeypatch.setattr(settings, "client_min_supported_version", "2.0.0")

    app = FastAPI()
    app.include_router(auth_router.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        # 低版本直接 426
        resp = client.post(
            "/api/auth/login",
            json={"username": "test", "password": "123"},
            headers={"X-Client-Version": "1.0.0"},
        )
        assert resp.status_code == 426
        assert "已停用" in resp.json()["detail"]

