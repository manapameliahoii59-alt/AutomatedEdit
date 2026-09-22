"""一键生成体验账号及7天后自动关闭桌面端权限功能集成测试。"""

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.admin_panel import setup_admin
from app.auth import hash_password
from app.config import settings
from app.database import Base
from app.deps import get_db
from app.models import User
from app.routers import auth
from app.services.user_access import assert_user_allowed, is_user_allowed, sync_expired_users


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_create_trial_user_endpoint(db_session, monkeypatch):
    """测试管理员通过 API 一键生成 7 天体验账号。"""
    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: db_session

    from app.admin_panel import get_admin_db
    app.dependency_overrides[get_admin_db] = lambda: db_session
    setup_admin(app)

    with TestClient(app, raise_server_exceptions=True) as client:
        # 1. 登录管理后台
        login = client.post(
            "/admin/login",
            data={
                "username": settings.admin_username,
                "password": settings.admin_password,
            },
            follow_redirects=False,
        )
        assert login.status_code == 302

        # 2. 一键生成体验账号（默认 7 天）
        resp = client.post(
            "/admin/users/create-trial",
            json={
                "trial_days": 7,
                "daily_clip_limit": 50,
                "daily_plan_limit": 50,
                "daily_download_limit": 50,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        user_data = data["user"]
        username = user_data["username"]
        password = user_data["password"]

        assert username.startswith("trial_")
        assert len(password) >= 8
        assert user_data["is_active"] is True
        assert user_data["trial_days"] == 7

        today = datetime.now(timezone.utc).date()
        expected_expiry = (today + timedelta(days=7)).isoformat()
        assert user_data["valid_until"] == expected_expiry
        assert "体验账号" in data["share_text"]

        # 3. 验证数据库中真实保存
        created_user = db_session.scalar(select(User).where(User.username == username))
        assert created_user is not None
        assert created_user.is_active is True
        assert created_user.plain_password == password
        assert created_user.valid_until == today + timedelta(days=7)
        assert created_user.daily_clip_limit == 50


def test_trial_user_can_login_without_iocpx(db_session):
    """测试生成的体验账号可直接在桌面端通过本地哈希登录，无需依赖外部第三方易投接口。"""
    today = datetime.now(timezone.utc).date()
    valid_until = today + timedelta(days=7)
    trial_user = User(
        username="trial_test01",
        password_hash=hash_password("Pass1234"),
        plain_password="Pass1234",
        role="user",
        is_active=True,
        valid_until=valid_until,
    )
    db_session.add(trial_user)
    db_session.commit()

    app = FastAPI()
    app.include_router(auth.router)
    app.dependency_overrides[get_db] = lambda: db_session

    client = TestClient(app)

    # 密码错误应被拒绝
    bad_resp = client.post(
        "/api/auth/login",
        json={"username": "trial_test01", "password": "WrongPassword"},
    )
    assert bad_resp.status_code in (400, 401)

    # 正确密码应成功签发 Token
    good_resp = client.post(
        "/api/auth/login",
        json={"username": "trial_test01", "password": "Pass1234"},
    )
    assert good_resp.status_code == 200
    res_data = good_resp.json()
    assert "access_token" in res_data
    assert res_data["user"]["username"] == "trial_test01"
    assert res_data["user"]["is_active"] is True


def test_trial_user_auto_deactivates_after_7_days(db_session):
    """测试体验账号超过 7 天后，自动将 is_active 翻转为 False，切断桌面端权限。"""
    today = date(2026, 9, 22)
    # 设置 7 天前已过期的账号（2026-09-20 到期）
    user = User(
        username="trial_expired",
        password_hash=hash_password("Pass1234"),
        plain_password="Pass1234",
        role="user",
        is_active=True,
        valid_until=date(2026, 9, 20),
        token_version=1,
    )
    db_session.add(user)
    db_session.commit()

    # 1. 验证在到期日前（2026-09-19）允许使用
    assert is_user_allowed(user, today=date(2026, 9, 19), db=db_session) is True
    assert user.is_active is True

    # 2. 在到期日（2026-09-20）当天允许使用
    assert is_user_allowed(user, today=date(2026, 9, 20), db=db_session) is True
    assert user.is_active is True

    # 3. 超过到期日（2026-09-21），自动关闭桌面端权限
    allowed = is_user_allowed(user, today=date(2026, 9, 21), db=db_session)
    assert allowed is False

    # 验证数据库中 is_active 自动持久化变为 False，token_version 自增
    db_session.refresh(user)
    assert user.is_active is False
    assert user.token_version == 2

    # 4. 再次调用断言应抛出 403
    with pytest.raises(Exception) as exc:
        assert_user_allowed(user, db=db_session)
    assert "无效" in str(exc.value.detail)


def test_sync_expired_users_batch_deactivation(db_session):
    """测试 sync_expired_users 批量检测并同步禁用已逾期的体验账号。"""
    today = date(2026, 9, 22)

    # 账号1：已过期，原本处于开启状态
    u1 = User(
        username="u1_expired",
        password_hash="x",
        is_active=True,
        valid_until=date(2026, 9, 15),
    )
    # 账号2：未过期，正常开启
    u2 = User(
        username="u2_active",
        password_hash="x",
        is_active=True,
        valid_until=date(2026, 9, 29),
    )
    # 账号3：已过期但原本就已经禁用
    u3 = User(
        username="u3_already_off",
        password_hash="x",
        is_active=False,
        valid_until=date(2026, 9, 10),
    )
    db_session.add_all([u1, u2, u3])
    db_session.commit()

    affected = sync_expired_users(db_session, today=today)
    assert affected == 1

    db_session.refresh(u1)
    db_session.refresh(u2)
    db_session.refresh(u3)

    assert u1.is_active is False  # 自动被置为 False
    assert u2.is_active is True   # 仍在体验期内保持 True
    assert u3.is_active is False  # 保持 False


def test_admin_users_page_renders_trial_button_and_modals(db_session):
    """测试 /admin/users 页面中，生成体验账号按钮位于重置表头左侧，且模态框正常输出。"""
    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: db_session

    from app.admin_panel import get_admin_db
    app.dependency_overrides[get_admin_db] = lambda: db_session
    setup_admin(app)

    with TestClient(app, raise_server_exceptions=True) as client:
        client.post(
            "/admin/login",
            data={
                "username": settings.admin_username,
                "password": settings.admin_password,
            },
            follow_redirects=False,
        )

        resp = client.get("/admin/users")
        assert resp.status_code == 200
        html = resp.text

        # 验证按钮存在
        assert "生成体验账号" in html
        assert "表格设置" in html

        # 验证生成体验账号按钮位于表格设置按钮的前面（左侧）
        idx_trial_btn = html.find("生成体验账号")
        idx_settings_btn = html.find("表格设置")
        assert idx_trial_btn != -1 and idx_settings_btn != -1
        assert idx_trial_btn < idx_settings_btn

        # 验证两个模态框结构均正常渲染
        assert "create-trial-modal" in html
        assert "trial-success-modal" in html
        assert "一键生成体验账号" in html
        assert "体验账号生成成功" in html

