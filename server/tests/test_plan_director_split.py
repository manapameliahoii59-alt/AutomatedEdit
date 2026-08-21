import sys
from pathlib import Path
from unittest.mock import patch

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


def test_split_ab_counts_matches_default_ratio():
    from app.services.plan_director import split_ab_counts

    assert split_ab_counts(15) == (6, 9)
    assert split_ab_counts(10) == (4, 6)
    assert split_ab_counts(5) == (2, 3)


def test_run_plan_split_ab_false_uses_single_group():
    """短片模式不分 A/B：只发起一次统一组请求。"""
    from app.services.plan_director import run_plan

    steps = [
        {"source_file": "1.mp4", "text": "开场对白一二三四", "end": 30.0},
        {"source_file": "1.mp4", "text": "转折对白五六七八", "end": 150.0},
    ]
    ordered = ["1.mp4"]
    calls: list[str] = []

    def _fake_call(**kwargs):
        calls.append(kwargs["group_type"])
        # 返回空，让循环耗尽但不走真实 LLM
        return None, 0.1, "skip"

    with patch("app.services.plan_director._call_deepseek", side_effect=_fake_call):
        try:
            run_plan(
                project_name="测试",
                steps=steps,
                ordered_files=ordered,
                api_keys_raw="sk-test",
                api_url="http://example.test",
                model_name="test",
                target_clips_count=5,
                min_duration_seconds=120,
                max_duration_seconds=300,
                split_ab=False,
            )
        except RuntimeError as exc:
            assert "未产出有效方案" in str(exc)

    assert calls
    assert all(g == "U" for g in calls)
    assert "A" not in calls and "B" not in calls


def test_run_plan_split_ab_true_uses_ab_groups():
    from app.services.plan_director import run_plan

    steps = [
        {"source_file": "1.mp4", "text": "开场对白一二三四", "end": 30.0},
        {"source_file": "2.mp4", "text": "转折对白五六七八", "end": 150.0},
    ]
    ordered = ["1.mp4", "2.mp4"]
    calls: list[str] = []

    def _fake_call(**kwargs):
        calls.append(kwargs["group_type"])
        return None, 0.1, "skip"

    with patch("app.services.plan_director._call_deepseek", side_effect=_fake_call):
        try:
            run_plan(
                project_name="测试",
                steps=steps,
                ordered_files=ordered,
                api_keys_raw="sk-test",
                api_url="http://example.test",
                model_name="test",
                target_clips_count=5,
                min_duration_seconds=150,
                max_duration_seconds=720,
                split_ab=True,
            )
        except RuntimeError as exc:
            assert "未产出有效方案" in str(exc)

    assert "A" in calls and "B" in calls
    assert "U" not in calls


def test_clamp_global_speed():
    from app.services.plan_director import clamp_global_speed

    assert clamp_global_speed(1.15) == 1.15
    assert clamp_global_speed(None) == 1.15
    assert clamp_global_speed(0.8) == 1.0
    assert clamp_global_speed(2.0) == 2.0
    assert clamp_global_speed(3.0) == 3.0
    assert clamp_global_speed(4.0) == 3.0


def test_clamp_plan_duration_allows_short():
    from app.services.plan_director import clamp_plan_duration_seconds

    assert clamp_plan_duration_seconds(120, default=150) == 120
    assert clamp_plan_duration_seconds(60, default=150) == 120
    assert clamp_plan_duration_seconds(1000, default=150) == 900


def test_short_and_long_prompts_are_independent():
    from app.services.plan_director import (
        _build_long_plan_prompt,
        _build_short_plan_prompt,
        _system_prompt_for_group,
    )

    short = _build_short_plan_prompt(
        count=5, min_duration_seconds=120, max_duration_seconds=360
    )
    long_a = _build_long_plan_prompt(
        count=5,
        min_duration_seconds=150,
        max_duration_seconds=720,
        group_type="A",
    )
    long_b = _build_long_plan_prompt(
        count=5,
        min_duration_seconds=150,
        max_duration_seconds=720,
        group_type="B",
    )

    assert "短片" in short and "开场" in short
    assert "高转化引流" in long_a
    assert "高转化引流" in long_b
    assert "A组" in long_a
    assert "B组" in long_b
    assert "A组" not in short and "B组" not in short
    assert "禁止从对白中间起切" in short
    assert "句前缓冲" in short
    assert "字幕残留" in short
    assert '"starts"' in short and '"ends"' in short
    assert "自动组合" in short
    assert '"clips"' not in short
    assert "空镜" not in long_a and "句前缓冲" not in long_a
    assert "字幕残留" not in long_a
    assert '"starts"' not in long_a
    assert "起始秒之前" not in long_a
    assert "某句台词的起始秒" not in long_a
    assert short != long_a
    assert _system_prompt_for_group(
        group_type="U", count=5, min_duration_seconds=120, max_duration_seconds=360
    ) == short
    assert "A组" in _system_prompt_for_group(
        group_type="A", count=5, min_duration_seconds=150, max_duration_seconds=720
    )


def test_mixed_prompt_is_independent():
    from app.services.plan_director import (
        _build_long_plan_prompt,
        _build_mixed_plan_prompt,
        _build_short_plan_prompt,
        _system_prompt_for_group,
    )

    short = _build_short_plan_prompt(
        count=5, min_duration_seconds=120, max_duration_seconds=360
    )
    long_a = _build_long_plan_prompt(
        count=5,
        min_duration_seconds=150,
        max_duration_seconds=720,
        group_type="A",
    )
    mixed_a = _build_mixed_plan_prompt(
        count=6,
        min_duration_seconds=120,
        max_duration_seconds=720,
        group_type="A",
    )
    mixed_b = _build_mixed_plan_prompt(
        count=9,
        min_duration_seconds=120,
        max_duration_seconds=720,
        group_type="B",
    )

    assert "混合模式" in mixed_a
    assert "混合模式" in mixed_b
    assert '"starts"' in mixed_a and '"ends"' in mixed_a
    assert '"clips"' not in mixed_a
    assert "A组" in mixed_a and "1.mp4" in mixed_a
    assert "B组" in mixed_b and "跨多集" in mixed_b
    assert "短片" not in mixed_a
    assert "高转化引流剪辑计划" not in mixed_a
    assert mixed_a != short
    assert mixed_a != long_a
    assert mixed_a != mixed_b
    assert _system_prompt_for_group(
        group_type="A",
        count=6,
        min_duration_seconds=120,
        max_duration_seconds=720,
        plan_mode="mixed",
    ) == mixed_a
    assert _system_prompt_for_group(
        group_type="B",
        count=9,
        min_duration_seconds=120,
        max_duration_seconds=720,
        plan_mode="mixed",
    ) == mixed_b
    # 长片默认仍走 clips 提示词，不被混合串扰
    assert '"clips"' in _system_prompt_for_group(
        group_type="A",
        count=5,
        min_duration_seconds=150,
        max_duration_seconds=720,
        plan_mode="long",
    )


def test_run_plan_mixed_uses_ab_and_plan_mode():
    from app.services.plan_director import run_plan

    steps = [
        {"source_file": "1.mp4", "text": "开场对白一二三四", "end": 30.0},
        {"source_file": "2.mp4", "text": "转折对白五六七八", "end": 150.0},
    ]
    ordered = ["1.mp4", "2.mp4"]
    calls: list[tuple[str, str]] = []

    def _fake_call(**kwargs):
        calls.append((kwargs["group_type"], kwargs.get("plan_mode", "")))
        return None, 0.1, "skip"

    with patch("app.services.plan_director._call_deepseek", side_effect=_fake_call):
        try:
            run_plan(
                project_name="测试",
                steps=steps,
                ordered_files=ordered,
                api_keys_raw="sk-test",
                api_url="http://example.test",
                model_name="test",
                target_clips_count=15,
                min_duration_seconds=120,
                max_duration_seconds=720,
                split_ab=True,
                plan_mode="mixed",
            )
        except RuntimeError as exc:
            assert "未产出有效方案" in str(exc)

    assert calls
    assert all(mode == "mixed" for _, mode in calls)
    assert "A" in {g for g, _ in calls} and "B" in {g for g, _ in calls}
    assert "U" not in {g for g, _ in calls}
