"""错误反馈 API 与管理后台集成测试。"""

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
from app.deps import get_db, get_optional_current_user
from app.models import ErrorReport, User
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
        username="testuser@example.com",
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


def test_post_error_report_anonymous(test_setup):
    app = test_setup["app"]
    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post(
            "/api/client/error-reports",
            json={
                "error_stage": "transcribe",
                "drama_name": "测试短剧A",
                "friendly_msg": "音频识别遇到异常，请检查视频文件后重试",
                "raw_error": "Traceback (most recent call last):\n  File 'pipeline.py', line 50\nValueError: Test error",
                "app_version": "1.0.1",
                "client_info": "OS: Windows-10 | Python: 3.12.0",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["id"] is not None

        # 检查数据库
        Session = test_setup["SessionLocal"]
        db = Session()
        report = db.query(ErrorReport).filter(ErrorReport.id == data["id"]).first()
        assert report is not None
        assert report.error_stage == "transcribe"
        assert report.drama_name == "测试短剧A"
        assert report.user_id is None
        assert report.username == "未登录用户"
        assert report.status == "pending"
        db.close()


def test_post_error_report_authenticated(test_setup):
    app = test_setup["app"]
    Session = test_setup["SessionLocal"]
    db = Session()
    user = db.query(User).first()
    db.close()

    # override get_optional_current_user to return this user
    app.dependency_overrides[get_optional_current_user] = lambda: user

    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post(
            "/api/client/error-reports",
            json={
                "error_stage": "plan",
                "drama_name": "测试短剧B",
                "friendly_msg": "分集策划失败",
                "raw_error": "Exception in plan",
                "app_version": "1.0.1",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

        db = Session()
        report = db.query(ErrorReport).filter(ErrorReport.id == data["id"]).first()
        assert report is not None
        assert report.user_id == user.id
        assert report.username == user.username
        db.close()


def test_admin_errors_page_and_actions(monkeypatch, test_setup):
    engine = test_setup["engine"]
    Session = test_setup["SessionLocal"]

    # 插入两条报错记录
    db = Session()
    rep1 = ErrorReport(
        user_id=test_setup["user_id"],
        username="testuser@example.com",
        app_version="1.0.0",
        error_stage="transcribe",
        drama_name="短剧X",
        friendly_msg="友好提示1",
        raw_error="Traceback demo 1",
        status="pending",
    )
    rep2 = ErrorReport(
        user_id=None,
        username="未登录用户",
        app_version="1.0.1",
        error_stage="render",
        drama_name="短剧Y",
        friendly_msg="友好提示2",
        raw_error="Traceback demo 2",
        status="resolved",
    )
    db.add_all([rep1, rep2])
    db.commit()
    rep1_id = rep1.id
    rep2_id = rep2.id
    db.close()

    monkeypatch.setattr("app.admin_panel.engine", engine)

    app = FastAPI()
    setup_admin(app)

    with TestClient(app, raise_server_exceptions=True) as client:
        # 登录后台
        login = client.post(
            "/admin/login",
            data={
                "username": settings.admin_username,
                "password": settings.admin_password,
            },
            follow_redirects=False,
        )
        assert login.status_code == 302

        # 访问 /admin/errors 页面
        resp = client.get("/admin/errors")
        assert resp.status_code == 200
        content = resp.text
        assert "短剧X" in content
        assert "短剧Y" in content
        assert "错误反馈" in content

        # 修改状态：将 rep1 改为 resolved
        status_resp = client.post(
            f"/admin/errors/{rep1_id}/status",
            data={"status": "resolved"},
            follow_redirects=False,
        )
        assert status_resp.status_code == 302

        db = Session()
        updated_rep1 = db.query(ErrorReport).filter(ErrorReport.id == rep1_id).first()
        assert updated_rep1.status == "resolved"
        db.close()

        # 删除 rep2
        del_resp = client.post(
            f"/admin/errors/{rep2_id}/delete",
            follow_redirects=False,
        )
        assert del_resp.status_code == 302

        db = Session()
        deleted_rep2 = db.query(ErrorReport).filter(ErrorReport.id == rep2_id).first()
        assert deleted_rep2 is None
        db.close()


def test_admin_errors_batch_resolve(monkeypatch, test_setup):
    engine = test_setup["engine"]
    Session = test_setup["SessionLocal"]

    db = Session()
    # 3 条待处理，1 条已解决，1 条已忽略
    p1 = ErrorReport(
        user_id=test_setup["user_id"],
        username="user1@example.com",
        app_version="1.0.0",
        error_stage="transcribe",
        drama_name="剧目Alpha",
        friendly_msg="识别失败1",
        raw_error="IndexError: list index out of range",
        status="pending",
    )
    p2 = ErrorReport(
        user_id=test_setup["user_id"],
        username="user1@example.com",
        app_version="1.0.0",
        error_stage="plan",
        drama_name="剧目Alpha",
        friendly_msg="策划失败2",
        raw_error="KeyError: choices",
        status="pending",
    )
    p3 = ErrorReport(
        user_id=None,
        username="未登录用户",
        app_version="1.0.1",
        error_stage="render",
        drama_name="剧目Beta",
        friendly_msg="渲染失败3",
        raw_error="TimeoutError: render timed out",
        status="pending",
    )
    r1 = ErrorReport(
        user_id=None,
        username="未登录用户",
        app_version="1.0.1",
        error_stage="general",
        drama_name="剧目Alpha",
        friendly_msg="已解决记录",
        raw_error="Some error",
        status="resolved",
    )
    i1 = ErrorReport(
        user_id=None,
        username="未登录用户",
        app_version="1.0.1",
        error_stage="general",
        drama_name="剧目Beta",
        friendly_msg="已忽略记录",
        raw_error="Some ignored error",
        status="ignored",
    )
    db.add_all([p1, p2, p3, r1, i1])
    db.commit()
    p1_id, p2_id, p3_id, r1_id, i1_id = p1.id, p2.id, p3.id, r1.id, i1.id
    db.close()

    monkeypatch.setattr("app.admin_panel.engine", engine)

    app = FastAPI()
    setup_admin(app)

    with TestClient(app, raise_server_exceptions=True) as client:
        # 1. 未登录请求 batch-resolve 需 302 重定向到登录页
        anon_resp = client.post("/admin/errors/batch-resolve", follow_redirects=False)
        assert anon_resp.status_code == 302
        assert "/admin/login" in anon_resp.headers.get("location", "")

        # 2. 登录后台
        login = client.post(
            "/admin/login",
            data={
                "username": settings.admin_username,
                "password": settings.admin_password,
            },
            follow_redirects=False,
        )
        assert login.status_code == 302

        # 3. 访问 /admin/errors 检查一键处理按钮与待处理统计 (3)
        page_resp = client.get("/admin/errors")
        assert page_resp.status_code == 200
        assert "一键处理" in page_resp.text
        assert "(3)" in page_resp.text

        # 4. 仅针对搜索结果 "剧目Alpha" 进行一键处理
        batch_resp_filtered = client.post(
            "/admin/errors/batch-resolve",
            data={"q": "剧目Alpha"},
            headers={"referer": "/admin/errors?q=%E5%89%A7%E7%9B%AEAlpha"},
            follow_redirects=False,
        )
        assert batch_resp_filtered.status_code == 302
        assert batch_resp_filtered.headers["location"] == "/admin/errors?q=%E5%89%A7%E7%9B%AEAlpha"

        # 验证数据库：p1, p2 变为 resolved；p3 依然为 pending；r1, i1 不变
        db = Session()
        assert db.get(ErrorReport, p1_id).status == "resolved"
        assert db.get(ErrorReport, p2_id).status == "resolved"
        assert db.get(ErrorReport, p3_id).status == "pending"
        assert db.get(ErrorReport, r1_id).status == "resolved"
        assert db.get(ErrorReport, i1_id).status == "ignored"
        db.close()

        # 5. 全量一键处理剩余的待处理记录
        batch_resp_all = client.post(
            "/admin/errors/batch-resolve",
            data={},
            headers={"referer": "/admin/errors"},
            follow_redirects=False,
        )
        assert batch_resp_all.status_code == 302

        # 验证数据库：p3 也变为 resolved
        db = Session()
        assert db.get(ErrorReport, p3_id).status == "resolved"
        assert db.get(ErrorReport, r1_id).status == "resolved"
        assert db.get(ErrorReport, i1_id).status == "ignored"
        db.close()

        # 6. 再次访问 /admin/errors，此时 pending 数量为 0，按钮应处于 disabled 状态
        page_resp2 = client.get("/admin/errors")
        assert page_resp2.status_code == 200
        assert "is-disabled" in page_resp2.text

