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


def test_clamp_plan_duration_allows_short():
    from app.services.plan_director import clamp_plan_duration_seconds

    assert clamp_plan_duration_seconds(120, default=150) == 120
    assert clamp_plan_duration_seconds(60, default=150) == 120
    assert clamp_plan_duration_seconds(1000, default=150) == 900
