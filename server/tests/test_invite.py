"""用户专属邀请码生成、防刷防互邀校验、动态奖励与管理后台测试。"""

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
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
from app.deps import get_current_user
from app.models import User, UserInviteRecord, SystemSetting
from app.routers import client
from app.services.invite_service import (
    bind_invite_code,
    ensure_user_invite_code,
    get_invite_config,
    get_user_invite_info,
    set_invite_config,
)


@pytest.fixture()
def in_memory_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        yield db
    finally:
        db.close()


def _create_test_user(db, username: str, clip_limit: int = 30) -> User:
    u = User(
        username=username,
        password_hash="fakehash",
        daily_clip_limit=clip_limit,
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_ensure_user_invite_code(in_memory_db):
    db = in_memory_db
    user = _create_test_user(db, "alice")
    assert not user.invite_code

    code = ensure_user_invite_code(db, user)
    assert len(code) == 6
    assert user.invite_code == code

    # 再次调用不会改变现有邀请码
    code2 = ensure_user_invite_code(db, user)
    assert code2 == code


def test_bind_invite_code_success(in_memory_db):
    db = in_memory_db
    inviter = _create_test_user(db, "inviter", clip_limit=30)
    invitee = _create_test_user(db, "invitee", clip_limit=30)
    inviter_code = ensure_user_invite_code(db, inviter)

    res = bind_invite_code(db, invitee, inviter_code)
    assert res["ok"] is True
    assert res["reward"] == 5
    assert res["new_clip_limit"] == 35
    assert res["inviter_username"] == "inviter"

    # 验证双方配额均增加 5
    db.refresh(inviter)
    db.refresh(invitee)
    assert inviter.daily_clip_limit == 35
    assert invitee.daily_clip_limit == 35
    assert invitee.invited_by_id == inviter.id

    # 验证流水记录
    records = db.query(UserInviteRecord).all()
    assert len(records) == 1
    assert records[0].inviter_id == inviter.id
    assert records[0].invitee_id == invitee.id
    assert records[0].reward_clip_limit == 5


def test_cannot_bind_self(in_memory_db):
    db = in_memory_db
    user = _create_test_user(db, "lonely")
    code = ensure_user_invite_code(db, user)

    with pytest.raises(HTTPException) as exc_info:
        bind_invite_code(db, user, code)
    assert exc_info.value.status_code == 400
    assert "不能使用自己的邀请码" in exc_info.value.detail


def test_cannot_bind_twice(in_memory_db):
    db = in_memory_db
    a = _create_test_user(db, "userA")
    b = _create_test_user(db, "userB")
    c = _create_test_user(db, "userC")

    code_a = ensure_user_invite_code(db, a)
    code_c = ensure_user_invite_code(db, c)

    # b 第一次绑定 a
    bind_invite_code(db, b, code_a)

    # b 尝试再次绑定 c
    with pytest.raises(HTTPException) as exc_info:
        bind_invite_code(db, b, code_c)
    assert exc_info.value.status_code == 400
    assert "不可重复兑换" in exc_info.value.detail


def test_cannot_mutual_invite(in_memory_db):
    db = in_memory_db
    a = _create_test_user(db, "userA")
    b = _create_test_user(db, "userB")

    code_a = ensure_user_invite_code(db, a)
    code_b = ensure_user_invite_code(db, b)

    # b 绑定 a
    bind_invite_code(db, b, code_a)

    # a 尝试反向绑定 b（拦截互邀闭环）
    with pytest.raises(HTTPException) as exc_info:
        bind_invite_code(db, a, code_b)
    assert exc_info.value.status_code == 400
    assert "双方不可互相绑定" in exc_info.value.detail


def test_invalid_invite_code(in_memory_db):
    db = in_memory_db
    u = _create_test_user(db, "testuser")

    with pytest.raises(HTTPException) as exc_info:
        bind_invite_code(db, u, "NONEXIST")
    assert exc_info.value.status_code == 404
    assert "邀请码不存在" in exc_info.value.detail


def test_dynamic_reward_config(in_memory_db):
    db = in_memory_db
    set_invite_config(db, reward_clip_limit=10, max_rewards_per_user=0)

    cfg = get_invite_config(db)
    assert cfg["reward_clip_limit"] == 10

    a = _create_test_user(db, "userA", clip_limit=30)
    b = _create_test_user(db, "userB", clip_limit=30)
    code_a = ensure_user_invite_code(db, a)

    res = bind_invite_code(db, b, code_a)
    assert res["reward"] == 10
    assert res["new_clip_limit"] == 40

    db.refresh(a)
    assert a.daily_clip_limit == 40


def test_max_rewards_per_user_limit(in_memory_db):
    db = in_memory_db
    # 设置最多只能拿 1 次奖励
    set_invite_config(db, reward_clip_limit=5, max_rewards_per_user=1)

    inviter = _create_test_user(db, "inviter", clip_limit=30)
    b = _create_test_user(db, "userB", clip_limit=30)
    c = _create_test_user(db, "userC", clip_limit=30)
    code = ensure_user_invite_code(db, inviter)

    # 第 1 次被邀请，双方都加
    bind_invite_code(db, b, code)
    db.refresh(inviter)
    assert inviter.daily_clip_limit == 35

    # 第 2 次被邀请，inviter 达到上限不再加，但 c 依然能获得奖励
    res = bind_invite_code(db, c, code)
    assert res["reward"] == 5
    assert res["new_clip_limit"] == 35

    db.refresh(inviter)
    db.refresh(c)
    assert inviter.daily_clip_limit == 35  # 上限生效，保持 35 不再加
    assert c.daily_clip_limit == 35       # 被邀请人正常增加


def test_feature_disabled(in_memory_db):
    db = in_memory_db
    set_invite_config(db, reward_clip_limit=5, is_enabled=False)

    a = _create_test_user(db, "userA")
    b = _create_test_user(db, "userB")
    code_a = ensure_user_invite_code(db, a)

    with pytest.raises(HTTPException) as exc_info:
        bind_invite_code(db, b, code_a)
    assert exc_info.value.status_code == 400
    assert "暂未开启" in exc_info.value.detail


def test_get_user_invite_info(in_memory_db):
    db = in_memory_db
    a = _create_test_user(db, "userA", clip_limit=30)
    b = _create_test_user(db, "userB", clip_limit=30)
    code_a = ensure_user_invite_code(db, a)

    info_a = get_user_invite_info(db, a)
    assert info_a["invite_code"] == code_a
    assert info_a["invitee_count"] == 0
    assert info_a["total_reward_clips"] == 0
    assert info_a["has_used_invite"] is False

    bind_invite_code(db, b, code_a)

    info_a_after = get_user_invite_info(db, a)
    assert info_a_after["invitee_count"] == 1
    assert info_a_after["total_reward_clips"] == 5

    info_b = get_user_invite_info(db, b)
    assert info_b["has_used_invite"] is True
    assert info_b["invited_by"] == "userA"


def test_api_client_endpoints(in_memory_db):
    db = in_memory_db
    alice = _create_test_user(db, "alice", clip_limit=30)
    bob = _create_test_user(db, "bob", clip_limit=30)
    alice_code = ensure_user_invite_code(db, alice)

    app = FastAPI()
    app.include_router(client.router)

    from app.database import get_db
    app.dependency_overrides[get_db] = lambda: db
    # 模拟当前用户为 bob
    app.dependency_overrides[get_current_user] = lambda: bob

    test_client = TestClient(app)

    # 1. 查询 bob 的邀请信息
    resp = test_client.get("/api/client/invite/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_used_invite"] is False
    assert len(data["invite_code"]) == 6

    # 2. bob 兑换 alice 的邀请码
    bind_resp = test_client.post("/api/client/invite/bind", json={"invite_code": alice_code})
    assert bind_resp.status_code == 200
    bind_data = bind_resp.json()
    assert bind_data["ok"] is True
    assert bind_data["reward"] == 5
    assert bind_data["new_clip_limit"] == 35

    # 3. 再次兑换应报错
    bind_again = test_client.post("/api/client/invite/bind", json={"invite_code": alice_code})
    assert bind_again.status_code == 400


def test_admin_invites_page_and_settings(monkeypatch, in_memory_db):
    from app.admin_panel import get_admin_db
    from app.deps import get_db

    db = in_memory_db
    _create_test_user(db, "alice", clip_limit=30)
    _create_test_user(db, "bob", clip_limit=30)

    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_admin_db] = lambda: db
    setup_admin(app)

    with TestClient(app, raise_server_exceptions=True) as client:
        # 登录管理后台
        login = client.post(
            "/admin/login",
            data={
                "username": settings.admin_username,
                "password": settings.admin_password,
            },
            follow_redirects=False,
        )
        assert login.status_code == 302

        # 访问 /admin/invites 页面，验证正确渲染不抛 500
        resp = client.get("/admin/invites")
        assert resp.status_code == 200
        assert "邀请管理" in resp.text
        assert "动态裂变奖励规则配置" in resp.text

        # 提交更新规则设置
        post_resp = client.post(
            "/admin/invites/settings",
            data={
                "reward_clip_limit": "8",
                "max_rewards_per_user": "50",
                "is_enabled": "1",
            },
            follow_redirects=False,
        )
        assert post_resp.status_code == 302
        assert "/admin/invites" in post_resp.headers["location"]

        cfg = get_invite_config(db)
        assert cfg["reward_clip_limit"] == 8
        assert cfg["max_rewards_per_user"] == 50
        assert cfg["is_enabled"] is True

