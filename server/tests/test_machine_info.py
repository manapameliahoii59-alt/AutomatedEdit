"""机器信息上报接口与管理后台集成测试。"""

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.admin_panel import setup_admin
from app.config import settings
from app.database import Base
from app.deps import get_current_user, get_db
from app.models import User, UserMachine
from app.routers import client as client_router


@pytest.fixture()
def test_setup():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = TestingSessionLocal()
    user = User(
        username="machuser@example.com",
        password_hash="hash",
        plain_password="pwd",
        role="user",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    app.dependency_overrides[get_db] = override_get_db
    app.include_router(client_router.router)

    return {
        "engine": engine,
        "SessionLocal": TestingSessionLocal,
        "app": app,
        "user_id": user.id,
    }


def _sample_payload():
    return {
        "os": "Windows-11-10.0.22631",
        "hostname": "PC-001",
        "cpu_name": "Intel(R) Core(TM) i7-9700 CPU @ 3.00GHz",
        "cpu_cores_logical": 8,
        "cpu_cores_physical": 8,
        "ram_total_mb": 16384,
        "ram_available_mb": 8192,
        "gpus": [{"name": "NVIDIA GeForce RTX 3060", "vendor": "NVIDIA", "vram_mb": 12288}],
        "gpu_summary": "NVIDIA GeForce RTX 3060",
        "client_version": "0.0.15",
    }


def _auth_override(test_setup):
    Session = test_setup["SessionLocal"]
    db = Session()
    user = db.query(User).filter(User.id == test_setup["user_id"]).first()
    db.close()
    test_setup["app"].dependency_overrides[get_current_user] = lambda: user
    return user


def test_report_machine_info_authenticated(test_setup):
    _auth_override(test_setup)
    with TestClient(test_setup["app"], raise_server_exceptions=True) as client:
        resp = client.post("/api/client/machine", json=_sample_payload())
        assert resp.status_code == 201
        assert resp.json()["ok"] is True

    db = test_setup["SessionLocal"]()
    row = db.query(UserMachine).filter(UserMachine.user_id == test_setup["user_id"]).first()
    assert row is not None
    assert row.cpu_name.startswith("Intel")
    assert row.ram_total_mb == 16384
    assert "RTX 3060" in row.gpu_summary
    assert row.gpus.startswith("[")
    db.close()


def test_report_machine_info_upsert_keeps_single_row(test_setup):
    _auth_override(test_setup)
    with TestClient(test_setup["app"], raise_server_exceptions=True) as client:
        client.post("/api/client/machine", json=_sample_payload())
        payload = _sample_payload()
        payload["cpu_name"] = "AMD Ryzen 9 5900X"
        payload["ram_total_mb"] = 32768
        resp = client.post("/api/client/machine", json=payload)
        assert resp.status_code == 201

    db = test_setup["SessionLocal"]()
    rows = db.query(UserMachine).filter(UserMachine.user_id == test_setup["user_id"]).all()
    assert len(rows) == 1
    assert rows[0].cpu_name == "AMD Ryzen 9 5900X"
    assert rows[0].ram_total_mb == 32768
    db.close()


def test_admin_machines_page(monkeypatch, test_setup):
    engine = test_setup["engine"]
    Session = test_setup["SessionLocal"]

    db = Session()
    db.add(
        UserMachine(
            user_id=test_setup["user_id"],
            cpu_name="Intel(R) Xeon(R) E5-2680",
            cpu_cores_logical=16,
            cpu_cores_physical=8,
            ram_total_mb=32768,
            ram_available_mb=16384,
            gpu_summary="NVIDIA GeForce RTX 3090",
            os="Windows-11",
            hostname="DEV-PC",
            client_version="0.0.15",
        )
    )
    db.commit()
    db.close()

    monkeypatch.setattr("app.admin_panel.engine", engine)

    app = FastAPI()
    setup_admin(app)

    with TestClient(app, raise_server_exceptions=True) as client:
        login = client.post(
            "/admin/login",
            data={
                "username": settings.admin_username,
                "password": settings.admin_password,
            },
            follow_redirects=False,
        )
        assert login.status_code == 302

        resp = client.get("/admin/machines")
        assert resp.status_code == 200
        content = resp.text
        assert "machuser@example.com" in content
        assert "RTX 3090" in content
        assert "机器信息" in content
