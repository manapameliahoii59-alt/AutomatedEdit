"""管理后台编辑页集成测试。"""

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.testclient import TestClient

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.admin_panel import AdminAuth, setup_admin
from app.config import settings
from app.database import Base
from app.models import User


@pytest.fixture()
def admin_client(monkeypatch, tmp_path):
    db_path = tmp_path / "admin_test.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(
        User(
            username="a@b.com",
            password_hash="hash",
            plain_password="pwd",
            role="user",
            is_active=True,
        )
    )
    db.commit()
    db.close()

    monkeypatch.setattr("app.admin_panel.engine", engine)

    app = FastAPI()
    admin = setup_admin(app)

    class NoAuth(AdminAuth):
        async def authenticate(self, request):
            return True

    admin.authentication_backend = NoAuth(secret_key="test")

    with TestClient(app, raise_server_exceptions=True) as client:
        client.post(
            "/admin/login",
            data={
                "username": settings.admin_username,
                "password": settings.admin_password,
            },
        )
        yield client


def test_user_edit_page_renders(admin_client):
    response = admin_client.get("/admin/user/edit/1")
    assert response.status_code == 200, response.text[:2000]
    assert "允许使用桌面端" in response.text
    assert "DeepSeek API Keys" in response.text
    assert "form-check form-switch" in response.text
    assert 'role="switch"' in response.text
    assert 'class="form-check-input"' in response.text
    assert 'class="form-control"' not in response.text.split("is_active")[1][:200]


def test_user_edit_saves_deepseek_keys(admin_client):
    save_resp = admin_client.post(
        "/admin/user/edit/1",
        data={
            "username": "a@b.com",
            "role": "user",
            "deepseek_keys": "sk-test-1,sk-test-2",
            "dashscope_key": "ds-key",
            "save": "Save",
        },
        follow_redirects=False,
    )
    assert save_resp.status_code == 302

    check_resp = admin_client.get("/admin/user/edit/1")
    assert check_resp.status_code == 200
    assert "sk-test-1,sk-test-2" in check_resp.text
    assert "ds-key" in check_resp.text


def test_user_edit_toggle_is_active(admin_client):
    save_resp = admin_client.post(
        "/admin/user/edit/1",
        data={"username": "a@b.com", "role": "user", "save": "Save"},
        follow_redirects=False,
    )
    assert save_resp.status_code == 302

    check_resp = admin_client.get("/admin/user/edit/1")
    assert check_resp.status_code == 200
    assert "checked" not in check_resp.text

    save_resp = admin_client.post(
        "/admin/user/edit/1",
        data={
            "username": "a@b.com",
            "role": "user",
            "is_active": "y",
            "save": "Save",
        },
        follow_redirects=False,
    )
    assert save_resp.status_code == 302

    check_resp = admin_client.get("/admin/user/edit/1")
    assert check_resp.status_code == 200
    assert "checked" in check_resp.text


def test_user_list_shows_deepseek_column(admin_client):
    response = admin_client.get("/admin/user/list")
    assert response.status_code == 200
    assert "DeepSeek Keys" in response.text
