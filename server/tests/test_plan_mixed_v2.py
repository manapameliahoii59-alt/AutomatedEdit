import json
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.database import Base
from app.models import User
from app.services.plan_director import (
    _build_mixed_plan_prompt_v2,
    _compose_short_plans_from_starts_ends_v2,
    _normalize_short_starts,
    _system_prompt_for_group,
    run_plan,
    split_ab_counts_v2,
)
from app.services.user_settings import get_user_settings, patch_user_settings


def test_split_ab_counts_v2():
    assert split_ab_counts_v2(15) == (4, 11)
    assert split_ab_counts_v2(10) == (4, 6)
    assert split_ab_counts_v2(5) == (4, 1)
    assert split_ab_counts_v2(20) == (4, 16)


def test_mixed_v2_prompts():
    prompt_a = _build_mixed_plan_prompt_v2(
        count=4,
        min_duration_seconds=120,
        max_duration_seconds=300,
        group_type="A",
    )
    prompt_b = _build_mixed_plan_prompt_v2(
        count=11,
        min_duration_seconds=120,
        max_duration_seconds=300,
        group_type="B",
    )

    # A 组规则验证
    assert "A组" in prompt_a
    assert "1.mp4 第0秒起" in prompt_a
    assert "不需要输出 starts 开头" in prompt_a
    assert '"ends"' in prompt_a
    assert '"starts"' not in prompt_a

    # B 组规则验证
    assert "B组" in prompt_b
    assert "严禁使用第1集开头作为切点" in prompt_b
    assert "score" in prompt_b
    assert "吸睛评分" in prompt_b
    assert '"starts"' in prompt_b and '"ends"' in prompt_b

    # _system_prompt_for_group 分发验证
    assert (
        _system_prompt_for_group(
            group_type="A",
            count=4,
            min_duration_seconds=120,
            max_duration_seconds=300,
            plan_mode="mixed",
            plan_strategy="v2",
        )
        == prompt_a
    )
    assert (
        _system_prompt_for_group(
            group_type="B",
            count=11,
            min_duration_seconds=120,
            max_duration_seconds=300,
            plan_mode="mixed",
            plan_strategy="v2",
        )
        == prompt_b
    )


def test_normalize_short_starts_score():
    raw = [
        {"se": "1.mp4", "st": 10.0, "score": 95},
        {"se": "2.mp4", "st": 20.0, "hook_score": 88},
        {"se": "3.mp4", "st": 30.0},
    ]
    norm = _normalize_short_starts(raw, ordered_files=["1.mp4", "2.mp4", "3.mp4"])
    assert norm[0]["score"] == 95.0
    assert norm[1]["score"] == 88.0
    assert norm[2]["score"] == 60.0  # 缺省 fallback


def test_compose_v2_group_a_fixed_intro():
    steps = [
        {"source_file": "1.mp4", "text": "第一集开头对白", "start": 0.5, "end": 10.0},
        {"source_file": "1.mp4", "text": "第一集转折对白", "start": 20.0, "end": 80.0},
        {"source_file": "2.mp4", "text": "第二集卡点台词必须精彩", "start": 10.0, "end": 40.0},
    ]
    ordered_files = ["1.mp4", "2.mp4"]
    episode_end_times = {"1.mp4": 100.0, "2.mp4": 100.0}

    ends_raw = [
        {
            "le": "2.mp4",
            "ct": "第二集卡点台词必须精彩",
            "hook": "引流标题A",
        }
    ]

    used_fingerprints = set()
    used_short_starts = {}

    plans = _compose_short_plans_from_starts_ends_v2(
        starts_raw=[],
        ends_raw=ends_raw,
        steps=steps,
        step_texts=[s["text"] for s in steps],
        ordered_files=ordered_files,
        episode_end_times=episode_end_times,
        min_dur=60.0,
        max_dur=180.0,
        target_count=4,
        used_fingerprints=used_fingerprints,
        used_short_starts=used_short_starts,
        project_name="测试A",
        date_str="0914",
        speed=1.0,
        group_type="A",
    )

    assert len(plans) == 1
    # 严格固定为 1.mp4 0.0s 起切
    assert plans[0]["files_config"]["first_episode_cut_start"] == 0.0
    assert plans[0]["files_config"]["last_episode"] == "2.mp4"
    assert used_short_starts.get("1.mp4_0.0") == 1


def test_compose_v2_group_b_rejects_ep1_zero_and_clusters():
    steps = [
        {"source_file": "1.mp4", "text": "第一集片头静音", "start": 0.0, "end": 0.5},
        {"source_file": "1.mp4", "text": "第一集台词一", "start": 1.5, "end": 5.0},
        {"source_file": "1.mp4", "text": "第一集中段台词", "start": 20.0, "end": 25.0},
        {"source_file": "2.mp4", "text": "第二集开头台词", "start": 5.0, "end": 10.0},
        {"source_file": "2.mp4", "text": "第二集中段转折台词", "start": 30.0, "end": 40.0},
        {"source_file": "3.mp4", "text": "第三集高潮台词一二三四", "start": 20.0, "end": 35.0},
        {"source_file": "4.mp4", "text": "第四集大结局悬念揭晓", "start": 15.0, "end": 30.0},
    ]
    ordered_files = ["1.mp4", "2.mp4", "3.mp4", "4.mp4"]
    episode_end_times = {
        "1.mp4": 60.0,
        "2.mp4": 60.0,
        "3.mp4": 60.0,
        "4.mp4": 60.0,
    }

    starts_raw = [
        # 1.mp4 0.0s -> 必须被硬性排除
        {"se": "1.mp4", "st": 0.0, "score": 99.0},
        # 1.mp4 18.0s -> 允许且高分 (跨集到 3.mp4/4.mp4)
        {"se": "1.mp4", "st": 18.0, "score": 95.0},
        # 2.mp4 2.0s -> 允许 (跨集到 3.mp4/4.mp4)
        {"se": "2.mp4", "st": 2.0, "score": 85.0},
    ]
    ends_raw = [
        {"le": "3.mp4", "ct": "第三集高潮台词一二三四", "hook": "结局3"},
        {"le": "4.mp4", "ct": "第四集大结局悬念揭晓", "hook": "结局4"},
    ]

    used_fingerprints = set()
    used_short_starts = {}

    plans = _compose_short_plans_from_starts_ends_v2(
        starts_raw=starts_raw,
        ends_raw=ends_raw,
        steps=steps,
        step_texts=[s["text"] for s in steps],
        ordered_files=ordered_files,
        episode_end_times=episode_end_times,
        min_dur=60.0,
        max_dur=240.0,
        target_count=4,
        used_fingerprints=used_fingerprints,
        used_short_starts=used_short_starts,
        project_name="测试B",
        date_str="0914",
        speed=1.0,
        group_type="B",
    )

    # 1.mp4 0.0s 绝对不能出现在任何计划中
    for p in plans:
        if p["files_config"].get("full_episodes") and p["files_config"]["full_episodes"][0] == "1.mp4":
            assert p["files_config"]["first_episode_cut_start"] > 1.0

    # 高分开头 (1.mp4 18.0s, score=95) 聚拢生成多条
    assert any("1.mp4" in k and v >= 1 for k, v in used_short_starts.items() if not k.endswith("_0.0"))


def test_run_plan_mixed_v2_end_to_end():
    steps = [
        {"source_file": "1.mp4", "text": "第1集开场台词", "start": 0.5, "end": 10.0},
        {"source_file": "1.mp4", "text": "第1集中段转折", "start": 20.0, "end": 80.0},
        {"source_file": "2.mp4", "text": "第2集卡点对白一二三四", "start": 15.0, "end": 60.0},
        {"source_file": "3.mp4", "text": "第3集卡点对白五六七八", "start": 20.0, "end": 70.0},
    ]
    ordered_files = ["1.mp4", "2.mp4", "3.mp4"]
    captured_calls: list[dict] = []

    def _fake_call(**kwargs):
        captured_calls.append(kwargs)
        g = kwargs["group_type"]
        if g == "A":
            # 返回 ends
            return (
                json.dumps(
                    {
                        "ends": [
                            {"le": "2.mp4", "ct": "第2集卡点对白一二三四", "hook": "A1"},
                            {"le": "3.mp4", "ct": "第3集卡点对白五六七八", "hook": "A2"},
                        ]
                    }
                ),
                0.1,
                None,
            )
        else:
            # 返回 starts + ends
            return (
                json.dumps(
                    {
                        "starts": [
                            {"se": "1.mp4", "st": 12.0, "score": 90},
                            {"se": "2.mp4", "st": 5.0, "score": 85},
                        ],
                        "ends": [
                            {"le": "3.mp4", "ct": "第3集卡点对白五六七八", "hook": "B1"},
                        ],
                    }
                ),
                0.1,
                None,
            )

    with patch("app.services.plan_director._call_deepseek", side_effect=_fake_call):
        plans = run_plan(
            project_name="V2测试",
            steps=steps,
            ordered_files=ordered_files,
            api_keys_raw="sk-mock",
            api_url="https://api.mock.test/v1",
            model_name="mock-v2",
            target_clips_count=15,
            min_duration_seconds=120,
            max_duration_seconds=300,
            plan_mode="mixed",
            plan_strategy="v2",
        )

    # 验证 DeepSeek 调用的参数包含 plan_strategy="v2"
    assert len(captured_calls) >= 2
    assert all(c.get("plan_strategy") == "v2" for c in captured_calls)

    # A 组分配 4，B 组分配 11
    a_calls = [c for c in captured_calls if c["group_type"] == "A"]
    b_calls = [c for c in captured_calls if c["group_type"] == "B"]
    assert a_calls[0]["count"] >= 4
    assert b_calls[0]["count"] >= 11
    assert len(plans) > 0


def test_user_settings_two_way_sync():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    user = User(
        username="user@test.com",
        password_hash="hash",
        plain_password="pwd",
        role="user",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # 初始默认 v1
    settings = get_user_settings(db, user.id)
    assert settings.plan.mixed_strategy == "v1"

    # 客户端同步修改为 v2
    patch_user_settings(db, user.id, {"plan": {"mixed_strategy": "v2"}})
    updated = get_user_settings(db, user.id)
    assert updated.plan.mixed_strategy == "v2"

    # 管理员改回 v1
    patch_user_settings(db, user.id, {"plan": {"mixed_strategy": "v1"}})
    updated2 = get_user_settings(db, user.id)
    assert updated2.plan.mixed_strategy == "v1"

    db.close()


def test_create_plan_job_fallback_strategy():
    from app.services import plan_jobs

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    user = User(
        username="job_user@test.com",
        password_hash="hash",
        plain_password="pwd",
        role="user",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # 将用户的 DB 配置设置为 v2
    patch_user_settings(db, user.id, {"plan": {"mixed_strategy": "v2"}})

    # 不传 plan_strategy，验证回退到 DB 中的 v2
    payload = {
        "project_name": "测试项目",
        "plan_mode": "mixed",
        "steps": [],
        "ordered_files": ["1.mp4"],
    }
    captured_payload = {}

    def _fake_run_job(job_id, payload_arg, plan_key, llm, *args, **kwargs):
        captured_payload.update(payload_arg)

    with patch.object(
        plan_jobs,
        "ensure_user_secret",
        return_value=type("Secret", (), {"plan_decrypt_key": "k" * 32})(),
    ), patch.object(
        plan_jobs,
        "resolve_plan_llm_config",
        return_value={
            "provider": "deepseek",
            "api_url": "https://api.deepseek.com/chat/completions",
            "model": "deepseek-v4-flash",
            "keys": "sk-test",
        },
    ), patch.object(
        plan_jobs, "_run_job", side_effect=_fake_run_job
    ):
        plan_jobs.create_plan_job(db, user.id, payload)
        assert captured_payload.get("plan_strategy") == "v2"

    db.close()
