"""混合模式 v3（广度铺开）策略测试。

v3 与 v2 的区别：
- A 组固定片头由 4 条收窄为 2 条；
- 每个开头切点最多出 2 条成片（v2 为 4 条）；
- 只有凑不满目标条数时，才按 2 → 4 → 不限 逐级放开单个开头的上限。

同时包含 v2 行为未受影响的回归断言。
"""

import json
import sys
from collections import Counter
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.plan_director import (  # noqa: E402
    _build_mixed_plan_prompt_v2,
    _build_mixed_plan_prompt_v3,
    _compose_short_plans_from_starts_ends_v2,
    _compose_short_plans_from_starts_ends_v3,
    _normalize_plan_strategy,
    _system_prompt_for_group,
    run_plan,
    split_ab_counts_v2,
    split_ab_counts_v3,
)

EPISODES = [f"{i}.mp4" for i in range(1, 16)]
EP_DUR = 300.0
EPISODE_END_TIMES = {ep: EP_DUR for ep in EPISODES}


def _build_steps():
    steps = []
    for ep in EPISODES:
        for k in range(28):
            steps.append(
                {
                    "source_file": ep,
                    "start": 10.0 * k + 1.0,
                    "end": 10.0 * k + 8.0,
                    "text": f"{ep}-句{k}",
                }
            )
    return steps


STEPS = _build_steps()
STEP_TEXTS = [s["text"] for s in STEPS]

ENDS_RAW = [
    {"le": ep, "ct": f"{ep}-句{k}", "hook": f"钩子-{ep}-{k}"}
    for ep in EPISODES
    for k in (5, 10, 15, 20)
]

STARTS_RAW = [
    {"se": ep, "st": 10.0 * k + 9.0, "score": 95.0 - idx * 5.0}
    for idx, ep in enumerate(EPISODES[:8])
    for k in (2, 6, 11)
]


def _compose(fn, *, target_count, cap, group_type, starts_raw=None, ends_raw=None,
             supplement=True):
    used_fingerprints = set()
    used_short_starts = {}
    plans = fn(
        starts_raw=STARTS_RAW if starts_raw is None else starts_raw,
        ends_raw=ENDS_RAW if ends_raw is None else ends_raw,
        steps=STEPS,
        step_texts=STEP_TEXTS,
        ordered_files=EPISODES,
        episode_end_times=EPISODE_END_TIMES,
        min_dur=120.0,
        max_dur=720.0,
        target_count=target_count,
        used_fingerprints=used_fingerprints,
        used_short_starts=used_short_starts,
        project_name="测试剧",
        date_str="0914",
        speed=1.0,
        supplement_asr_starts=supplement,
        same_start_limit=cap,
        group_type=group_type,
    )
    return plans or []


def _start_key(plan):
    cfg = plan["files_config"]
    first_ep = cfg["full_episodes"][0] if cfg["full_episodes"] else cfg["last_episode"]
    return first_ep, cfg["first_episode_cut_start"]


def test_split_ab_counts_v3():
    """v3 固定片头 2 条，其余全部给 B 组。"""
    assert split_ab_counts_v3(15) == (2, 13)
    assert split_ab_counts_v3(20) == (2, 18)
    assert split_ab_counts_v3(10) == (2, 8)
    assert split_ab_counts_v3(5) == (2, 3)
    # 不影响 v2
    assert split_ab_counts_v2(15) == (4, 11)


def test_normalize_plan_strategy():
    assert _normalize_plan_strategy("v3") == "v3"
    assert _normalize_plan_strategy("V3") == "v3"
    assert _normalize_plan_strategy("v2") == "v2"
    assert _normalize_plan_strategy("v1") == "v1"
    assert _normalize_plan_strategy(None) == "v1"
    assert _normalize_plan_strategy("") == "v1"
    assert _normalize_plan_strategy("garbage") == "v1"


def test_mixed_v3_prompts():
    prompt_a = _build_mixed_plan_prompt_v3(
        count=2, min_duration_seconds=120, max_duration_seconds=300, group_type="A"
    )
    prompt_b = _build_mixed_plan_prompt_v3(
        count=13, min_duration_seconds=120, max_duration_seconds=300, group_type="B"
    )

    # A 组：只出 ends，开头固定第 1 集片头
    assert "A组" in prompt_a
    assert "1.mp4 第0秒起" in prompt_a
    assert "不需要输出 starts 开头" in prompt_a
    assert '"starts"' not in prompt_a

    # B 组：跨集、禁首集片头、带 score，且强调开头分散
    assert "B组" in prompt_b
    assert "严禁使用第1集开头作为切点" in prompt_b
    assert "score" in prompt_b
    assert "分散" in prompt_b

    # v3 与 v2 提示词必须不同（v3 额外要求开头分散）
    prompt_b_v2 = _build_mixed_plan_prompt_v2(
        count=13, min_duration_seconds=120, max_duration_seconds=300, group_type="B"
    )
    assert prompt_b != prompt_b_v2
    assert "分散" not in prompt_b_v2

    # _system_prompt_for_group 分发到 v3
    assert (
        _system_prompt_for_group(
            group_type="B",
            count=13,
            min_duration_seconds=120,
            max_duration_seconds=300,
            plan_mode="mixed",
            plan_strategy="v3",
        )
        == prompt_b
    )
    # v2 仍分发到 v2 提示词（行为未变）
    assert (
        _system_prompt_for_group(
            group_type="B",
            count=13,
            min_duration_seconds=120,
            max_duration_seconds=300,
            plan_mode="mixed",
            plan_strategy="v2",
        )
        == prompt_b_v2
    )


def test_compose_v3_group_a_fixed_intro_two_clips():
    """A 组：开头固定 1.mp4 第 0 秒，条数收窄为 2。"""
    plans = _compose(
        _compose_short_plans_from_starts_ends_v3,
        target_count=2,
        cap=2,
        group_type="A",
        starts_raw=[],
    )
    assert len(plans) == 2
    for plan in plans:
        assert plan["files_config"]["first_episode_cut_start"] == 0.0
    assert set(_start_key(p) for p in plans) == {("1.mp4", 0.0)}


def test_compose_v3_group_b_cap_is_two():
    """B 组：每个开头最多 2 条，且不同开头数量明显多于 v2。"""
    plans_v3 = _compose(
        _compose_short_plans_from_starts_ends_v3,
        target_count=13,
        cap=2,
        group_type="B",
    )
    counts_v3 = Counter(_start_key(p) for p in plans_v3)

    assert len(plans_v3) == 13
    assert max(counts_v3.values()) <= 2
    assert len(counts_v3) >= 7

    plans_v2 = _compose(
        _compose_short_plans_from_starts_ends_v2,
        target_count=11,
        cap=4,
        group_type="B",
    )
    counts_v2 = Counter(_start_key(p) for p in plans_v2)

    # v3 覆盖的开头更多，v2 仍允许单开头 4 条（回归保护）
    assert len(counts_v3) > len(counts_v2)
    assert max(counts_v2.values()) <= 4


def test_compose_v3_group_b_never_uses_ep1_intro():
    """B 组必须排除 1.mp4 片头切点，避免与 A 组撞开头。"""
    plans = _compose(
        _compose_short_plans_from_starts_ends_v3,
        target_count=13,
        cap=2,
        group_type="B",
    )
    for plan in plans:
        ep, st = _start_key(plan)
        assert not (ep == "1.mp4" and st <= 1.0)


def test_compose_v3_group_b_releases_cap_when_short():
    """候选开头不足时，逐级放开 2 条上限。"""
    scarce_starts = [
        {"se": "2.mp4", "st": 21.0, "score": 95.0},
        {"se": "3.mp4", "st": 61.0, "score": 90.0},
        {"se": "4.mp4", "st": 111.0, "score": 85.0},
    ]
    plans = _compose(
        _compose_short_plans_from_starts_ends_v3,
        target_count=13,
        cap=2,
        group_type="B",
        starts_raw=scarce_starts,
        supplement=False,
    )
    counts = Counter(_start_key(p) for p in plans)

    assert len(plans) == 13
    assert max(counts.values()) > 2, "候选不足时应放开单开头上限"


def test_v3_does_not_change_v2_composer():
    """v3 上线不得改变 v2 组合结果（同输入同输出）。"""
    plans_v2 = _compose(
        _compose_short_plans_from_starts_ends_v2,
        target_count=11,
        cap=4,
        group_type="B",
    )
    assert len(plans_v2) == 11
    assert len(Counter(_start_key(p) for p in plans_v2)) == 4

    plans_a_v2 = _compose(
        _compose_short_plans_from_starts_ends_v2,
        target_count=4,
        cap=4,
        group_type="A",
        starts_raw=[],
    )
    assert len(plans_a_v2) == 4
    assert set(_start_key(p) for p in plans_a_v2) == {("1.mp4", 0.0)}


def _build_e2e_fixture():
    """端到端用的轻量剧本：15 集，每集 100 秒、10 句。"""
    episodes = [f"{i}.mp4" for i in range(1, 16)]
    steps = []
    for ep in episodes:
        for k in range(10):
            steps.append(
                {
                    "source_file": ep,
                    "start": 10.0 * k + 1.0,
                    "end": 10.0 * k + 8.0,
                    "text": f"{ep}-句{k}",
                }
            )
    return episodes, steps


def test_run_plan_mixed_v3_end_to_end():
    """v3 端到端：策略透传、A/B 按 2:13 分组、A 组固定片头、B 组每开头不超 2 条。"""
    episodes, steps = _build_e2e_fixture()
    captured_calls: list[dict] = []

    def _fake_call(**kwargs):
        captured_calls.append(kwargs)
        if kwargs["group_type"] == "A":
            # A 组只输出 ends
            ends = [
                {"le": ep, "ct": f"{ep}-句{k}", "hook": f"A-{ep}-{k}"}
                for ep in episodes
                for k in (2, 5, 8)
            ]
            return json.dumps({"ends": ends}), 0.1, None
        # B 组输出 starts + ends
        starts = [
            {"se": ep, "st": 10.0 * k + 9.0, "score": 95.0 - idx}
            for idx, ep in enumerate(episodes[:8])
            for k in (2, 5, 8)
        ]
        ends = [
            {"le": ep, "ct": f"{ep}-句{k}", "hook": f"B-{ep}-{k}"}
            for ep in episodes
            for k in (2, 5, 8)
        ]
        return json.dumps({"starts": starts, "ends": ends}), 0.1, None

    with patch("app.services.plan_director._call_deepseek", side_effect=_fake_call):
        plans = run_plan(
            project_name="V3测试",
            steps=steps,
            ordered_files=episodes,
            api_keys_raw="sk-mock",
            api_url="https://api.mock.test/v1",
            model_name="mock-v3",
            target_clips_count=15,
            min_duration_seconds=120,
            max_duration_seconds=720,
            plan_mode="mixed",
            plan_strategy="v3",
        )

    assert captured_calls
    # 策略版本必须原样透传到 LLM 调用
    assert all(c.get("plan_strategy") == "v3" for c in captured_calls)

    a_calls = [c for c in captured_calls if c["group_type"] == "A"]
    b_calls = [c for c in captured_calls if c["group_type"] == "B"]
    assert a_calls, "v3 应产出 A 组任务"
    assert b_calls, "v3 应产出 B 组任务"
    # v3 分组：A 组 2 条，B 组拿其余 13 条
    assert a_calls[0]["count"] >= 2
    assert b_calls[0]["count"] >= 13

    assert len(plans) > 0
    # 序号连续且不重复
    assert len({p["title"] for p in plans}) == len(plans)

    # A 组必须固定为第 1 集第 0 秒
    a_plans = [
        p for p in plans if p["files_config"]["first_episode_cut_start"] == 0.0
    ]
    assert a_plans, "v3 A 组应产出固定片头成片"
    for plan in a_plans:
        assert plan["files_config"]["full_episodes"][0] == "1.mp4"

    # B 组：候选充足时每个开头最多 2 条
    b_plans = [
        p for p in plans if p["files_config"]["first_episode_cut_start"] != 0.0
    ]
    if b_plans:
        counts = Counter(_start_key(p) for p in b_plans)
        assert max(counts.values()) <= 2, "B 组单开头不应超过 2 条"
        for plan in b_plans:
            ep, st = _start_key(plan)
            assert not (ep == "1.mp4" and st <= 1.0)


def test_run_plan_mixed_v3_prompt_is_v3():
    """v3 端到端必须命中 v3 提示词，且不落到 v2/v1 分支。"""
    episodes, steps = _build_e2e_fixture()
    prompts: list[str] = []

    def _fake_call(**kwargs):
        from app.services.plan_director import _system_prompt_for_group

        prompts.append(
            _system_prompt_for_group(
                group_type=kwargs["group_type"],
                count=kwargs["count"],
                min_duration_seconds=kwargs["min_duration_seconds"],
                max_duration_seconds=kwargs["max_duration_seconds"],
                plan_mode=kwargs.get("plan_mode", "mixed"),
                plan_strategy=kwargs.get("plan_strategy", "v1"),
            )
        )
        return json.dumps({"ends": []}), 0.1, None

    with patch("app.services.plan_director._call_deepseek", side_effect=_fake_call):
        try:
            run_plan(
                project_name="V3提示词",
                steps=steps,
                ordered_files=episodes,
                api_keys_raw="sk-mock",
                api_url="https://api.mock.test/v1",
                model_name="mock-v3",
                target_clips_count=15,
                min_duration_seconds=120,
                max_duration_seconds=720,
                plan_mode="mixed",
                plan_strategy="v3",
            )
        except Exception:
            pass  # 无 ends 时 run_plan 会抛错，此处只关心提示词内容

    assert prompts, "应至少调用一次模型"
    b_prompts = [p for p in prompts if "B组" in p]
    assert b_prompts, "应命中 B 组提示词"
    assert all("分散" in p for p in b_prompts), "v3 B 组提示词应强调开头分散"
