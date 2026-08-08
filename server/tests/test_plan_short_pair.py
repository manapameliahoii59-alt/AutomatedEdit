import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.services.plan_director import (
    _compose_short_plans_from_starts_ends,
    _parse_short_starts_ends,
)


def test_parse_short_starts_ends_native():
    raw = """
    {"starts":[{"se":"1.mp4","st":10.5}],
     "ends":[{"le":"2.mp4","ct":"你给我站住","hook":"结局逆转"}]}
    """
    starts, ends = _parse_short_starts_ends(raw)
    assert starts == [{"se": "1.mp4", "st": 10.5}]
    assert ends[0]["le"] == "2.mp4"
    assert ends[0]["ct"] == "你给我站住"


def test_parse_short_starts_ends_from_legacy_clips():
    raw = """
    {"clips":[
      {"se":"1.mp4","st":5,"le":"3.mp4","ct":"原文台词甲","hook":"钩子A"},
      {"se":"2.mp4","st":8,"le":"4.mp4","ct":"原文台词乙","hook":"钩子B"}
    ]}
    """
    starts, ends = _parse_short_starts_ends(raw)
    assert len(starts) == 2 and len(ends) == 2
    assert starts[0]["se"] == "1.mp4"
    assert ends[1]["ct"] == "原文台词乙"


def test_compose_pairs_by_duration():
    steps = [
        {"source_file": "1.mp4", "start": 10.0, "end": 12.0, "text": "开场垫"},
        {"source_file": "1.mp4", "start": 20.0, "end": 22.0, "text": "开场句"},
        {"source_file": "1.mp4", "start": 100.0, "end": 110.0, "text": "中间过渡台词"},
        {"source_file": "1.mp4", "start": 140.0, "end": 150.0, "text": "你给我站住别跑"},
        {"source_file": "1.mp4", "start": 200.0, "end": 210.0, "text": "另一段悬念对白"},
    ]
    ordered = ["1.mp4"]
    episode_end_times = {"1.mp4": 300.0}
    starts = [{"se": "1.mp4", "st": 21.0}]
    ends = [
        {"le": "1.mp4", "ct": "你给我站住别跑", "hook": "钩子1"},
        {"le": "1.mp4", "ct": "另一段悬念对白", "hook": "钩子2"},
    ]
    plans = _compose_short_plans_from_starts_ends(
        starts_raw=starts,
        ends_raw=ends,
        steps=steps,
        step_texts=[s["text"] for s in steps],
        ordered_files=ordered,
        episode_end_times=episode_end_times,
        min_dur=100,
        max_dur=160,
        target_count=5,
        used_fingerprints=set(),
        used_short_starts={},
        project_name="测",
        date_str="0807",
        speed=1.15,
        supplement_asr_starts=False,
    )
    assert len(plans) >= 1
    for p in plans:
        st = p["files_config"]["first_episode_cut_start"]
        cut = p["files_config"]["last_episode_cut_point"]
        assert 100 <= (cut - st) <= 160
        # 不得贴着上一句结束（开场句 prev=12 → floor>=12.3）
        assert st >= 12.3


def test_max_same_short_start_is_two_fifths():
    from app.services.plan_director import max_same_short_start

    assert max_same_short_start(15) == 6
    assert max_same_short_start(10) == 4
    assert max_same_short_start(5) == 2
    assert max_same_short_start(1) == 1
    assert max_same_short_start(0) == 1


def _pair_fixture():
    steps = [
        {"source_file": "1.mp4", "start": 10.0, "end": 12.0, "text": "开场垫"},
        {"source_file": "1.mp4", "start": 20.0, "end": 22.0, "text": "开场句"},
        {"source_file": "1.mp4", "start": 100.0, "end": 110.0, "text": "第一集中段"},
        {"source_file": "1.mp4", "start": 140.0, "end": 150.0, "text": "你给我站住别跑"},
        {"source_file": "2.mp4", "start": 10.0, "end": 12.0, "text": "二集开场"},
        {"source_file": "2.mp4", "start": 20.0, "end": 22.0, "text": "二集起切"},
        {"source_file": "2.mp4", "start": 140.0, "end": 150.0, "text": "跨集悬念对白"},
    ]
    ordered = ["1.mp4", "2.mp4"]
    episode_end_times = {"1.mp4": 300.0, "2.mp4": 300.0}
    return steps, ordered, episode_end_times


def test_compose_group_b_rejects_same_episode():
    steps, ordered, episode_end_times = _pair_fixture()
    starts = [{"se": "1.mp4", "st": 21.0}]
    ends_same = [{"le": "1.mp4", "ct": "你给我站住别跑", "hook": "同集"}]
    plans_same = _compose_short_plans_from_starts_ends(
        starts_raw=starts,
        ends_raw=ends_same,
        steps=steps,
        step_texts=[s["text"] for s in steps],
        ordered_files=ordered,
        episode_end_times=episode_end_times,
        min_dur=100,
        max_dur=160,
        target_count=5,
        used_fingerprints=set(),
        used_short_starts={},
        project_name="测",
        date_str="0807",
        speed=1.15,
        supplement_asr_starts=False,
        group_type="B",
    )
    assert plans_same == []

    ends_cross = [{"le": "2.mp4", "ct": "跨集悬念对白", "hook": "跨集"}]
    plans_cross = _compose_short_plans_from_starts_ends(
        starts_raw=starts,
        ends_raw=ends_cross,
        steps=steps,
        step_texts=[s["text"] for s in steps],
        ordered_files=ordered,
        episode_end_times=episode_end_times,
        min_dur=100,
        max_dur=500,
        target_count=5,
        used_fingerprints=set(),
        used_short_starts={},
        project_name="测",
        date_str="0807",
        speed=1.15,
        supplement_asr_starts=False,
        group_type="B",
    )
    assert len(plans_cross) >= 1
    for p in plans_cross:
        assert p["files_config"]["last_episode"] == "2.mp4"
        assert "1.mp4" in (
            p["files_config"]["full_episodes"] + [p["files_config"]["last_episode"]]
        )


def test_compose_group_a_only_accepts_first_episode_start():
    steps, ordered, episode_end_times = _pair_fixture()
    ends = [{"le": "2.mp4", "ct": "跨集悬念对白", "hook": "钩子"}]
    plans_reject = _compose_short_plans_from_starts_ends(
        starts_raw=[{"se": "2.mp4", "st": 21.0}],
        ends_raw=ends,
        steps=steps,
        step_texts=[s["text"] for s in steps],
        ordered_files=ordered,
        episode_end_times=episode_end_times,
        min_dur=100,
        max_dur=500,
        target_count=5,
        used_fingerprints=set(),
        used_short_starts={},
        project_name="测",
        date_str="0807",
        speed=1.15,
        supplement_asr_starts=False,
        group_type="A",
    )
    assert plans_reject == []

    plans_ok = _compose_short_plans_from_starts_ends(
        starts_raw=[{"se": "1.mp4", "st": 21.0}],
        ends_raw=ends,
        steps=steps,
        step_texts=[s["text"] for s in steps],
        ordered_files=ordered,
        episode_end_times=episode_end_times,
        min_dur=100,
        max_dur=500,
        target_count=5,
        used_fingerprints=set(),
        used_short_starts={},
        project_name="测",
        date_str="0807",
        speed=1.15,
        supplement_asr_starts=False,
        group_type="A",
    )
    assert len(plans_ok) >= 1
    for p in plans_ok:
        # A 组必须以 1.mp4 开场（full_episodes 首集或同集结束）
        full = p["files_config"]["full_episodes"]
        last = p["files_config"]["last_episode"]
        assert (full and full[0] == "1.mp4") or (not full and last == "1.mp4")
        assert p["files_config"]["first_episode_cut_start"] >= 0