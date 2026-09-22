"""用户专属邀请码生成、防刷防互邀校验、动态奖励与管理后台测试。"""

import sys
from datetime import datetime, timedelta
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
    get_user_active_invite_bonus,
    get_user_effective_clip_limit,
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

    # 验证双方有效配额均增加 5，且流水记录正确包含 30 天有效期
    db.refresh(inviter)
    db.refresh(invitee)
    assert get_user_effective_clip_limit(db, inviter) == 35
    assert get_user_effective_clip_limit(db, invitee) == 35
    assert invitee.invited_by_id == inviter.id

    # 验证流水记录
    records = db.query(UserInviteRecord).all()
    assert len(records) == 1
    assert records[0].inviter_id == inviter.id
    assert records[0].invitee_id == invitee.id
    assert records[0].reward_clip_limit == 5
    assert records[0].valid_days == 30
    assert records[0].expires_at is not None


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

    assert get_user_effective_clip_limit(db, a) == 40
    assert get_user_effective_clip_limit(db, b) == 40


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
    assert get_user_effective_clip_limit(db, inviter) == 35
    assert get_user_effective_clip_limit(db, b) == 35

    # 第 2 次被邀请，inviter 达到上限不再加，但 c 依然能获得奖励
    res = bind_invite_code(db, c, code)
    assert res["reward"] == 5
    assert res["new_clip_limit"] == 35

    assert get_user_effective_clip_limit(db, inviter) == 35  # 上限生效，保持 35 不再加
    assert get_user_effective_clip_limit(db, c) == 35  # 被邀请人正常增加


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
                "reward_valid_days": "15",
                "max_permanent_clip_limit": "20",
                "is_enabled": "1",
            },
            follow_redirects=False,
        )
        assert post_resp.status_code == 302
        assert "/admin/invites" in post_resp.headers["location"]

        cfg = get_invite_config(db)
        assert cfg["reward_clip_limit"] == 8
        assert cfg["max_rewards_per_user"] == 50
        assert cfg["reward_valid_days"] == 15
        assert cfg["max_permanent_clip_limit"] == 20
        assert cfg["is_enabled"] is True


def test_invite_reward_expiry_after_30_days(in_memory_db):
    """测试邀请奖励在30天有效期内生效，逾期后平稳自然失效。"""
    from app.services.daily_quota import build_daily_quota

    db = in_memory_db
    set_invite_config(db, reward_clip_limit=5, reward_valid_days=30, max_rewards_per_user=10)

    user_a = _create_test_user(db, "userA", clip_limit=30)
    user_b = _create_test_user(db, "userB", clip_limit=30)
    code_a = ensure_user_invite_code(db, user_a)

    bind_res = bind_invite_code(db, user_b, code_a)
    assert bind_res["reward"] == 5
    assert bind_res["valid_days"] == 30
    assert bind_res["expires_at"] is not None

    record = db.query(UserInviteRecord).filter_by(invitee_id=user_b.id).first()
    assert record is not None
    assert record.valid_days == 30
    assert record.expires_at is not None

    start_time = record.created_at or datetime.now()

    # 1. 刚绑定或 15 天后：在有效期内，双方额度均为 35
    day15 = start_time + timedelta(days=15)
    assert get_user_active_invite_bonus(db, user_a.id, now=day15) == 5
    assert get_user_effective_clip_limit(db, user_a, now=day15) == 35
    assert get_user_active_invite_bonus(db, user_b.id, now=day15) == 5
    assert get_user_effective_clip_limit(db, user_b, now=day15) == 35

    # 验证 daily_quota 服务配额正确加上临时加成
    quota_day15 = build_daily_quota(db, user_a, now=day15)
    assert quota_day15.clip_limit == 35

    # 2. 31 天后：已超过 30 天，临时奖励自然失效，回退至基准额度 30
    day31 = start_time + timedelta(days=31)
    assert get_user_active_invite_bonus(db, user_a.id, now=day31) == 0
    assert get_user_effective_clip_limit(db, user_a, now=day31) == 30
    assert get_user_active_invite_bonus(db, user_b.id, now=day31) == 0
    assert get_user_effective_clip_limit(db, user_b, now=day31) == 30

    # 验证 daily_quota 服务在过期后回退
    quota_day31 = build_daily_quota(db, user_a, now=day31)
    assert quota_day31.clip_limit == 30

    # 3. 验证个人中心邀请信息接口在过期前后的展示
    info_day15 = get_user_invite_info(db, user_a, now=day15)
    assert info_day15["active_bonus_clips"] == 5
    assert info_day15["total_reward_clips"] == 5
    assert info_day15["daily_clip_limit"] == 35

    info_day31 = get_user_invite_info(db, user_a, now=day31)
    assert info_day31["active_bonus_clips"] == 0
    assert info_day31["total_reward_clips"] == 5  # 历史累计奖励依然记录
    assert info_day31["daily_clip_limit"] == 30


def test_invite_reward_permanent_when_zero(in_memory_db):
    """测试 reward_valid_days 为 0 时为永久奖励。"""
    db = in_memory_db
    set_invite_config(db, reward_clip_limit=5, reward_valid_days=0)

    user_a = _create_test_user(db, "userA", clip_limit=30)
    user_b = _create_test_user(db, "userB", clip_limit=30)
    code_a = ensure_user_invite_code(db, user_a)

    bind_res = bind_invite_code(db, user_b, code_a)
    assert bind_res["valid_days"] == 0
    assert bind_res["expires_at"] is None

    record = db.query(UserInviteRecord).filter_by(invitee_id=user_b.id).first()
    assert record.valid_days == 0
    assert record.expires_at is None

    # 即使过了 365 天，依然有效
    far_future = datetime.now() + timedelta(days=365)
    assert get_user_active_invite_bonus(db, user_a.id, now=far_future) == 5
    assert get_user_effective_clip_limit(db, user_a, now=far_future) == 35
    assert get_user_effective_clip_limit(db, user_b, now=far_future) == 35


def test_invite_permanent_cap_at_15_and_temp_beyond(in_memory_db):
    """测试用户需求核心逻辑：
    1. 初始剪辑上限为 10 首；
    2. 邀请 1 个人增加 5 首，未超永久上限 15，永久额度变为 15，临时额度为 0；
    3. 再次邀请 1 个人，已达永久上限 15，超出部分记为 30 天临时额度 5，总有效额度为 20；
    4. 30 天临时额度到期后，额度自然回落至永久额度 15（不会回到 10）。
    """
    db = in_memory_db
    set_invite_config(
        db,
        reward_clip_limit=5,
        reward_valid_days=30,
        max_permanent_clip_limit=15,
        max_rewards_per_user=0,
    )

    user_a = _create_test_user(db, "userA", clip_limit=10)
    user_b = _create_test_user(db, "userB", clip_limit=10)
    user_c = _create_test_user(db, "userC", clip_limit=10)

    code_a = ensure_user_invite_code(db, user_a)

    # 1. user_a 邀请 user_b
    bind_res_b = bind_invite_code(db, user_b, code_a)
    assert bind_res_b["reward"] == 5

    # user_a 永久额度从 10 提升至 15
    db.refresh(user_a)
    db.refresh(user_b)
    assert user_a.daily_clip_limit == 15
    assert get_user_active_invite_bonus(db, user_a.id) == 0
    assert get_user_effective_clip_limit(db, user_a) == 15

    # user_b 永久额度从 10 提升至 15
    assert user_b.daily_clip_limit == 15
    assert get_user_active_invite_bonus(db, user_b.id) == 0
    assert get_user_effective_clip_limit(db, user_b) == 15

    rec_b = db.query(UserInviteRecord).filter_by(invitee_id=user_b.id).first()
    assert rec_b.inviter_temp_reward == 0
    assert rec_b.invitee_temp_reward == 0

    # 2. user_a 再次邀请 user_c
    bind_res_c = bind_invite_code(db, user_c, code_a)
    assert bind_res_c["reward"] == 5

    db.refresh(user_a)
    db.refresh(user_c)
    # user_a 已达到 15 永久上限，daily_clip_limit 依然保持 15
    assert user_a.daily_clip_limit == 15
    # 超出部分 5 记为临时额度
    assert get_user_active_invite_bonus(db, user_a.id) == 5
    # 总有效上限 = 15(永久) + 5(临时) = 20
    assert get_user_effective_clip_limit(db, user_a) == 20

    # user_c 初始为 10，空间为 5，因此全部增加为永久额度 15
    assert user_c.daily_clip_limit == 15
    assert get_user_active_invite_bonus(db, user_c.id) == 0
    assert get_user_effective_clip_limit(db, user_c) == 15

    rec_c = db.query(UserInviteRecord).filter_by(invitee_id=user_c.id).first()
    assert rec_c.inviter_temp_reward == 5
    assert rec_c.inviter_expires_at is not None
    assert rec_c.invitee_temp_reward == 0

    # 3. 经过 15 天：临时额度仍在有效期内，user_a 仍为 20
    day15 = datetime.now() + timedelta(days=15)
    assert get_user_active_invite_bonus(db, user_a.id, now=day15) == 5
    assert get_user_effective_clip_limit(db, user_a, now=day15) == 20

    # 4. 经过 31 天：临时额度过期，user_a 额度平稳回归永久上限 15，而不是回退到 10
    day31 = datetime.now() + timedelta(days=31)
    assert get_user_active_invite_bonus(db, user_a.id, now=day31) == 0
    assert get_user_effective_clip_limit(db, user_a, now=day31) == 15

    # user_b 与 user_c 均为永久额度 15，不受 30 天限制
    assert get_user_effective_clip_limit(db, user_b, now=day31) == 15
    assert get_user_effective_clip_limit(db, user_c, now=day31) == 15


def test_invite_partial_split_headroom(in_memory_db):
    """测试部分空间填补永久额度、剩余部分转为临时额度的场景：
    例如用户当前额度为 12，永久上限为 15，单次奖励为 5。
    空间仅剩 3：
    - 永久提升 +3（物理额度变 15）
    - 临时提升 +2（30天有效期）
    - 当前总有效额度 = 15 + 2 = 17
    - 30天后临时额度失效，回归 15
    """
    db = in_memory_db
    set_invite_config(
        db,
        reward_clip_limit=5,
        reward_valid_days=30,
        max_permanent_clip_limit=15,
    )

    user_a = _create_test_user(db, "userA", clip_limit=12)
    user_b = _create_test_user(db, "userB", clip_limit=10)
    code_a = ensure_user_invite_code(db, user_a)

    bind_invite_code(db, user_b, code_a)

    db.refresh(user_a)
    assert user_a.daily_clip_limit == 15  # 12 + 3 = 15 永久
    assert get_user_active_invite_bonus(db, user_a.id) == 2  # 临时 +2
    assert get_user_effective_clip_limit(db, user_a) == 17

    rec = db.query(UserInviteRecord).filter_by(invitee_id=user_b.id).first()
    assert rec.inviter_temp_reward == 2
    assert rec.invitee_temp_reward == 0  # user_b 从 10 升到 15 全部是永久

    day31 = datetime.now() + timedelta(days=31)
    assert get_user_active_invite_bonus(db, user_a.id, now=day31) == 0
    assert get_user_effective_clip_limit(db, user_a, now=day31) == 15



