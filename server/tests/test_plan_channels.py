"""多模型渠道池与混合模式调度策略单元测试与集成测试。"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

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
from app.models import User, UserSecret, LlmChannel, LlmGroup
from app.services.plan_secrets import resolve_plan_llm_group
from app.services.plan_director import run_plan


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


def test_resolve_plan_llm_group_logic(in_memory_db):
    db = in_memory_db
    ch1 = LlmChannel(
        name="Channel 1",
        provider="deepseek",
        api_url="https://api.deepseek.com",
        model_name="deepseek-v4-flash",
        api_keys="sk-ch1",
        is_active=True,
    )
    ch2 = LlmChannel(
        name="Channel 2",
        provider="zhipu",
        api_url="https://open.bigmodel.cn/api/paas/v4",
        model_name="glm-5.3",
        api_keys="sk-ch2",
        is_active=True,
    )
    db.add_all([ch1, ch2])
    db.commit()

    grp1 = LlmGroup(
        name="Default Serial Group",
        dispatch_mode="serial",
        channel_ids=f"{ch1.id},{ch2.id}",
        max_loops_per_channel=2,
        is_default=True,
    )
    grp2 = LlmGroup(
        name="Custom Parallel Group",
        dispatch_mode="parallel",
        channel_ids=f"{ch2.id}",
        max_loops_per_channel=3,
        is_default=False,
    )
    db.add_all([grp1, grp2])
    db.commit()

    user = User(
        username="test_multi@example.com",
        password_hash="hash",
        plain_password="pwd",
        role="user",
        is_active=True,
    )
    db.add(user)
    db.commit()

    secret = UserSecret(
        user_id=user.id,
        plan_group_id=None,
        deepseek_keys="sk-single",
    )
    db.add(secret)
    db.commit()

    # 默认使用 is_default 组
    resolved = resolve_plan_llm_group(db, user.id)
    assert resolved is not None
    assert resolved["group_id"] == grp1.id
    assert resolved["dispatch_mode"] == "serial"
    assert len(resolved["channels"]) == 2
    assert resolved["channels"][0]["name"] == "Channel 1"

    # 用户指定组 grp2
    secret.plan_group_id = grp2.id
    db.commit()
    resolved_custom = resolve_plan_llm_group(db, user.id)
    assert resolved_custom is not None
    assert resolved_custom["group_id"] == grp2.id
    assert resolved_custom["dispatch_mode"] == "parallel"
    assert len(resolved_custom["channels"]) == 1

    # 用户指定 0（独立单模型模式）
    secret.plan_group_id = 0
    db.commit()
    resolved_zero = resolve_plan_llm_group(db, user.id)
    assert resolved_zero is None


def test_mixed_mode_strict_guard():
    # 验证非混合模式（例如 long）传入 llm_group 时直接被忽略，不触发多渠道
    mock_llm_group = {
        "group_id": 999,
        "dispatch_mode": "serial",
        "channels": [
            {
                "id": 1,
                "name": "Ch1",
                "provider": "deepseek",
                "api_url": "https://api.deepseek.com",
                "model_name": "deepseek-v4-flash",
                "api_keys": ["sk-1"],
            }
        ],
    }

    steps = [
        {"source_file": "1.mp4", "start": 0.0, "end": 180.0, "text": "测试台词"}
    ]
    ordered_files = ["1.mp4"]

    # 调用 plan_mode="long"，应走旧长片逻辑，使用传入的单模型
    with patch("app.services.plan_director._call_deepseek") as mock_ds:
        mock_ds.return_value = (
            json.dumps({"clips": [{"se": "1.mp4", "st": 0.0, "le": "1.mp4", "ct": "测试台词"}]}),
            0.1,
            "",
        )
        plans = run_plan(
            project_name="测试项目",
            steps=steps,
            ordered_files=ordered_files,
            api_keys_raw="sk-test",
            api_url="https://api.deepseek.com",
            model_name="deepseek-chat",
            provider="deepseek",
            plan_mode="long",
            target_clips_count=1,
            min_duration_seconds=50,
            max_duration_seconds=300,
            llm_group=mock_llm_group,
        )
        assert mock_ds.called
        call_kwargs = mock_ds.call_args.kwargs
        # 单模型调用时 provider 必定为 fake 的 deepseek
        assert call_kwargs.get("provider") == "deepseek"
        assert len(plans) >= 1


def test_mixed_serial_cascade_stagnation_cutoff():
    # 模拟串行调度：渠道 1 第一轮成功产出，第二轮停滞触发 break，由渠道 2 接手完成
    called_providers = []

    def fake_call_deepseek(**kwargs):
        provider = kwargs.get("provider")
        called_providers.append(provider)
        if provider == "deepseek":
            if called_providers.count("deepseek") == 1:
                # 产生 1 条有效结果
                return (
                    json.dumps(
                        {
                            "starts": [{"se": "1.mp4", "st": 0.0, "score": 90}],
                            "ends": [{"le": "1.mp4", "ct": "第一段台词卡点", "hook": "标题1"}],
                        }
                    ),
                    0.1,
                    "",
                )
            else:
                # 停滞：空结果，触发停滞熔断跳至下一个渠道
                return (json.dumps({"starts": [], "ends": []}), 0.1, "")
        else:
            # zhipu 接手，产出后续结果
            return (
                json.dumps(
                    {
                        "starts": [{"se": "1.mp4", "st": 15.0, "score": 88}],
                        "ends": [{"le": "1.mp4", "ct": "第二段台词卡点", "hook": "标题2"}],
                    }
                ),
                0.1,
                "",
            )

    steps = [
        {"source_file": "1.mp4", "start": 0.0, "end": 10.0, "text": "开头台词"},
        {"source_file": "1.mp4", "start": 160.0, "end": 170.0, "text": "第一段台词卡点"},
        {"source_file": "1.mp4", "start": 180.0, "end": 190.0, "text": "第二段开头台词"},
        {"source_file": "1.mp4", "start": 350.0, "end": 360.0, "text": "第二段台词卡点"},
    ]
    ordered_files = ["1.mp4"]

    llm_group = {
        "group_id": 1,
        "dispatch_mode": "serial",
        "max_loops_per_channel": 2,
        "channels": [
            {
                "id": 1,
                "name": "DS Channel",
                "provider": "deepseek",
                "api_url": "https://api.deepseek.com",
                "model_name": "deepseek-v4-flash",
                "api_keys": ["sk-1"],
            },
            {
                "id": 2,
                "name": "GLM Channel",
                "provider": "zhipu",
                "api_url": "https://open.bigmodel.cn",
                "model_name": "glm-5.3",
                "api_keys": ["sk-2"],
            },
        ],
    }

    with patch("app.services.plan_director._call_deepseek", side_effect=fake_call_deepseek):
        plans = run_plan(
            project_name="测试项目",
            steps=steps,
            ordered_files=ordered_files,
            api_keys_raw="sk-fallback",
            api_url="https://api.deepseek.com",
            model_name="deepseek-chat",
            provider="deepseek",
            plan_mode="mixed",
            target_clips_count=2,
            min_duration_seconds=120,
            max_duration_seconds=300,
            plan_strategy="v1",
            llm_group=llm_group,
        )

    assert len(plans) == 2
    assert "deepseek" in called_providers
    assert "zhipu" in called_providers


def test_mixed_parallel_merge():
    # 模拟并发融合调度：两家模型并发执行
    def fake_call_deepseek(**kwargs):
        provider = kwargs.get("provider")
        if provider == "deepseek":
            return (
                json.dumps(
                    {
                        "starts": [{"se": "1.mp4", "st": 0.0, "score": 95}],
                        "ends": [{"le": "1.mp4", "ct": "卡点台词A", "hook": "标题A"}],
                    }
                ),
                0.1,
                "",
            )
        else:
            return (
                json.dumps(
                    {
                        "starts": [{"se": "1.mp4", "st": 10.0, "score": 85}],
                        "ends": [{"le": "1.mp4", "ct": "卡点台词B", "hook": "标题B"}],
                    }
                ),
                0.1,
                "",
            )

    steps = [
        {"source_file": "1.mp4", "start": 0.0, "end": 10.0, "text": "开头台词"},
        {"source_file": "1.mp4", "start": 160.0, "end": 170.0, "text": "卡点台词A"},
        {"source_file": "1.mp4", "start": 330.0, "end": 340.0, "text": "卡点台词B"},
    ]
    ordered_files = ["1.mp4"]

    llm_group = {
        "group_id": 2,
        "dispatch_mode": "parallel",
        "channels": [
            {
                "id": 1,
                "name": "DS Channel",
                "provider": "deepseek",
                "api_url": "https://api.deepseek.com",
                "model_name": "deepseek-v4-flash",
                "api_keys": ["sk-1"],
            },
            {
                "id": 2,
                "name": "GLM Channel",
                "provider": "zhipu",
                "api_url": "https://open.bigmodel.cn",
                "model_name": "glm-5.3",
                "api_keys": ["sk-2"],
            },
        ],
    }

    with patch("app.services.plan_director._call_deepseek", side_effect=fake_call_deepseek):
        plans = run_plan(
            project_name="测试项目",
            steps=steps,
            ordered_files=ordered_files,
            api_keys_raw="sk-fallback",
            api_url="https://api.deepseek.com",
            model_name="deepseek-chat",
            provider="deepseek",
            plan_mode="mixed",
            target_clips_count=2,
            min_duration_seconds=120,
            max_duration_seconds=300,
            plan_strategy="v1",
            llm_group=llm_group,
        )

    assert len(plans) >= 1


@pytest.fixture()
def admin_client_fixture(monkeypatch, tmp_path):
    db_path = tmp_path / "channels_test.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(
        User(
            username="admin_user@test.com",
            password_hash="hash",
            plain_password="pwd",
            role="user",
            is_active=True,
        )
    )
    db.commit()
    db.close()

    monkeypatch.setattr("app.admin_panel.engine", engine)
    from app.deps import get_db

    def override_get_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app = FastAPI()
    app.dependency_overrides[get_db] = override_get_db
    setup_admin(app)

    with TestClient(app, raise_server_exceptions=True) as client:
        client.post(
            "/admin/login",
            data={
                "username": settings.admin_username,
                "password": settings.admin_password,
            },
        )
        yield client, Session


def test_admin_channel_and_group_crud(admin_client_fixture):
    client, Session = admin_client_fixture

    # 1. 访问 /admin/channels 页面
    res = client.get("/admin/channels")
    assert res.status_code == 200
    assert "大模型渠道与策略调度" in res.text

    # 2. 新增一个渠道
    save_ch_res = client.post(
        "/admin/channels/channel/save",
        data={
            "channel_id": "",
            "name": "Test DS Channel",
            "provider": "deepseek",
            "api_url": "https://api.deepseek.com",
            "model_name": "deepseek-v4-flash",
            "api_keys": "sk-123456",
            "priority": "100",
            "is_active": "y",
            "thinking_enabled": "",
        },
        follow_redirects=True,
    )
    assert save_ch_res.status_code == 200

    db = Session()
    ch = db.query(LlmChannel).filter(LlmChannel.name == "Test DS Channel").first()
    assert ch is not None
    ch_id = ch.id
    db.close()

    # 3. 新增一个策略调度组
    save_grp_res = client.post(
        "/admin/channels/group/save",
        data={
            "group_id": "",
            "name": "Test Serial Group",
            "dispatch_mode": "serial",
            "channel_ids": [str(ch_id)],
            "max_loops_per_channel": "2",
            "is_default": "y",
        },
        follow_redirects=True,
    )
    assert save_grp_res.status_code == 200

    db = Session()
    grp = db.query(LlmGroup).filter(LlmGroup.name == "Test Serial Group").first()
    assert grp is not None
    assert grp.dispatch_mode == "serial"
    assert grp.is_default is True
    db.close()

    # 4. 在用户编辑页保存 plan_group_id
    db = Session()
    user = db.query(User).filter(User.username == "admin_user@test.com").first()
    u_id = user.id
    db.close()

    user_save_res = client.post(
        f"/admin/users/{u_id}",
        data={
            "username": "admin_user@test.com",
            "plan_group_id": str(grp.id),
        },
        follow_redirects=True,
    )
    assert user_save_res.status_code == 200

    db = Session()
    sec = db.query(UserSecret).filter(UserSecret.user_id == u_id).first()
    assert sec is not None
    assert sec.plan_group_id == grp.id
    db.close()


def test_admin_channels_siliconflow_and_tongyi(admin_client_fixture):
    client, Session = admin_client_fixture

    models_to_test = [
        ("siliconflow", "Qwen/Qwen3.8-27B", "SF Qwen"),
        ("siliconflow", "deepseek-ai/DeepSeek-V4-Flash", "SF DS V4 Flash"),
        ("siliconflow", "deepseek-ai/DeepSeek-V3.2", "SF DS V3.2"),
        ("tongyi", "qwen3.7-flash", "TY Qwen Flash"),
    ]

    for prov, model, name in models_to_test:
        resp = client.post(
            "/admin/channels/channel/save",
            data={
                "channel_id": "",
                "name": name,
                "provider": prov,
                "api_url": "",
                "model_name": model,
                "api_keys": "sk-test-key",
                "priority": "10",
                "is_active": "y",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

    # 访问 channels 页面验证标签与模型均正确渲染
    get_res = client.get("/admin/channels")
    assert get_res.status_code == 200
    assert "硅基流动" in get_res.text
    assert "通义千问" in get_res.text
    assert "Qwen/Qwen3.8-27B" in get_res.text
    assert "deepseek-ai/DeepSeek-V4-Flash" in get_res.text
    assert "deepseek-ai/DeepSeek-V3.2" in get_res.text
    assert "qwen3.7-flash" in get_res.text

    # 测试连通性探测接口
    with patch("httpx.Client") as mock_client_cls:
        mock_client = mock_client_cls.return_value.__enter__.return_value
        mock_resp = mock_client.post.return_value
        mock_resp.status_code = 200
        mock_resp.text = '{"choices": []}'

        sf_test = client.post(
            "/admin/channels/channel/test",
            data={
                "provider": "siliconflow",
                "api_url": "",
                "model_name": "Qwen/Qwen3.8-27B",
                "api_key": "sk-sf-test",
            },
        )
        assert sf_test.status_code == 200
        assert sf_test.json()["success"] is True

        ty_test = client.post(
            "/admin/channels/channel/test",
            data={
                "provider": "tongyi",
                "api_url": "",
                "model_name": "qwen3.7-flash",
                "api_key": "sk-ty-test",
            },
        )
        assert ty_test.status_code == 200
        assert ty_test.json()["success"] is True

