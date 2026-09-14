"""渲染遥测上报接口测试（编码器 + 分辨率 + 缓存/合成耗时）。"""

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

from app.database import Base
from app.deps import get_current_user, get_db
from app.models import UsageEvent, User
from app.routers import client as client_router


@pytest.fixture()
def test_setup():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = SessionLocal()
    user = User(
        username="usage@example.com",
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
        session = SessionLocal()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    app.dependency_overrides[get_db] = override_get_db
    app.include_router(client_router.router)
    return {"SessionLocal": SessionLocal, "app": app, "user_id": user.id}


def _auth_override(test_setup):
    Session = test_setup["SessionLocal"]
    db = Session()
    user = db.query(User).filter(User.id == test_setup["user_id"]).first()
    db.close()
    test_setup["app"].dependency_overrides[get_current_user] = lambda: user
    return user


def test_report_usage_persists_render_telemetry(test_setup):
    _auth_override(test_setup)
    payload = {
        "event": "batch_all_render",
        "success": True,
        "duration_ms": 12345,
        "encoder": "h264_nvenc",
        "resolution": "720x1280",
        "cache_ms": 8000,
        "compose_ms": 4345,
        "render_engine": "legacy",
        "client_version": "0.0.16",
    }
    with TestClient(test_setup["app"], raise_server_exceptions=True) as client:
        resp = client.post("/api/client/usage", json=payload)
        assert resp.status_code == 201
        assert resp.json()["ok"] is True

    db = test_setup["SessionLocal"]()
    row = (
        db.query(UsageEvent)
        .filter(UsageEvent.user_id == test_setup["user_id"])
        .first()
    )
    assert row is not None
    assert row.event == "batch_all_render"
    assert row.encoder == "h264_nvenc"
    assert row.resolution == "720x1280"
    assert row.cache_ms == 8000
    assert row.compose_ms == 4345
    assert row.render_engine == "legacy"
    db.close()


def test_report_usage_without_telemetry_uses_defaults(test_setup):
    _auth_override(test_setup)
    with TestClient(test_setup["app"], raise_server_exceptions=True) as client:
        resp = client.post(
            "/api/client/usage", json={"event": "some_other_event"}
        )
        assert resp.status_code == 201

    db = test_setup["SessionLocal"]()
    row = (
        db.query(UsageEvent)
        .filter(UsageEvent.user_id == test_setup["user_id"])
        .first()
    )
    assert row is not None
    assert row.encoder == ""
    assert row.resolution == ""
    assert row.cache_ms == 0
    assert row.compose_ms == 0
    assert row.render_engine == ""
    assert row.plan_model == ""
    assert row.transcribe_ms == 0
    assert row.plan_ms == 0
    assert row.render_ms == 0
    db.close()


def test_report_usage_persists_model_and_stage_timings(test_setup):
    _auth_override(test_setup)
    payload = {
        "event": "batch_all_render",
        "success": True,
        "duration_ms": 65000,
        "meta": "测试剧目",
        "plan_mode": "mixed",
        "plan_model": "deepseek-v4-flash",
        "transcribe_ms": 12000,
        "plan_ms": 23000,
        "render_ms": 30000,
        "encoder": "h264_nvenc",
        "resolution": "720x1280",
        "render_engine": "current",
    }
    with TestClient(test_setup["app"], raise_server_exceptions=True) as client:
        resp = client.post("/api/client/usage", json=payload)
        assert resp.status_code == 201
        assert resp.json()["ok"] is True

    db = test_setup["SessionLocal"]()
    row = (
        db.query(UsageEvent)
        .filter(UsageEvent.user_id == test_setup["user_id"])
        .order_by(UsageEvent.id.desc())
        .first()
    )
    assert row is not None
    assert row.plan_model == "deepseek-v4-flash"
    assert row.transcribe_ms == 12000
    assert row.plan_ms == 23000
    assert row.render_ms == 30000
    assert row.duration_ms == 65000
    db.close()


def test_report_usage_auto_resolves_plan_model_on_plan_event(test_setup, monkeypatch):
    from app.services import plan_secrets

    _auth_override(test_setup)

    def _fake_resolve(db, user_id):
        return {
            "provider": "deepseek",
            "api_url": "https://api.deepseek.com",
            "model": "deepseek-auto-model",
            "keys": "sk-xxx",
            "thinking_enabled": False,
        }

    monkeypatch.setattr(
        "app.services.plan_secrets.resolve_plan_llm_config", _fake_resolve
    )

    payload = {
        "event": "plan_drama",
        "meta": "自动策划测试剧",
        "plan_mode": "short",
        "plan_ms": 18000,
    }
    with TestClient(test_setup["app"], raise_server_exceptions=True) as client:
        resp = client.post("/api/client/usage", json=payload)
        assert resp.status_code == 201

    db = test_setup["SessionLocal"]()
    row = (
        db.query(UsageEvent)
        .filter(UsageEvent.user_id == test_setup["user_id"])
        .order_by(UsageEvent.id.desc())
        .first()
    )
    assert row is not None
    assert row.plan_model == "deepseek-auto-model"
    assert row.plan_ms == 18000
    db.close()
