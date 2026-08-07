import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.services.plan_director import (
    MIN_BEFORE_SPEECH_SECONDS,
    MIN_START_GAP_SECONDS,
    POST_UTTERANCE_PAD_SECONDS,
    START_LEAD_IN_SECONDS,
    _compress_script,
    _pick_short_start_for_duration,
    _snap_start_to_utterance,
)


def _expected_short_preferred(prev_end: float, utter_start: float) -> float:
    floor = prev_end + POST_UTTERANCE_PAD_SECONDS
    latest = utter_start - MIN_BEFORE_SPEECH_SECONDS
    preferred = floor + (latest - floor) * 0.55
    lead_pref = utter_start - START_LEAD_IN_SECONDS
    if floor <= lead_pref <= latest:
        preferred = max(preferred, lead_pref)
    return round(min(max(floor, preferred), latest), 3)


def test_snap_start_inside_utterance_keeps_lead_in():
    """长片路径（min_gap=0）：仍按句首 - lead_in。"""
    steps = [
        {"source_file": "1.mp4", "start": 10.0, "end": 20.0, "text": "第一句"},
        {"source_file": "1.mp4", "start": 22.0, "end": 30.0, "text": "第二句"},
    ]
    assert _snap_start_to_utterance(steps, "1.mp4", 15.5) == round(
        10.0 - START_LEAD_IN_SECONDS, 3
    )


def test_snap_start_in_gap_keeps_lead_in_before_next():
    steps = [
        {"source_file": "1.mp4", "start": 10.0, "end": 20.0, "text": "第一句"},
        {"source_file": "1.mp4", "start": 25.0, "end": 30.0, "text": "第二句"},
    ]
    assert _snap_start_to_utterance(steps, "1.mp4", 21.0) == round(
        max(20.0, 25.0 - START_LEAD_IN_SECONDS), 3
    )


def test_snap_start_tight_gap_without_min_gap_clamps_to_prev_end():
    steps = [
        {"source_file": "1.mp4", "start": 10.0, "end": 20.0, "text": "第一句"},
        {"source_file": "1.mp4", "start": 20.5, "end": 28.0, "text": "紧接"},
    ]
    assert _snap_start_to_utterance(steps, "1.mp4", 21.0) == 20.0


def test_short_min_gap_skips_tight_and_uses_next():
    steps = [
        {"source_file": "1.mp4", "start": 10.0, "end": 20.0, "text": "第一句"},
        {"source_file": "1.mp4", "start": 20.3, "end": 22.0, "text": "紧接"},
        {"source_file": "1.mp4", "start": 24.0, "end": 30.0, "text": "有空隙"},
    ]
    # 紧接句 raw_gap=0.3 < 1.1；下一句 gap=2.0，且带句后垫
    assert _snap_start_to_utterance(
        steps,
        "1.mp4",
        21.0,
        lead_in_seconds=START_LEAD_IN_SECONDS,
        min_gap_seconds=MIN_START_GAP_SECONDS,
    ) == _expected_short_preferred(22.0, 24.0)


def test_short_min_gap_rejects_when_no_roomy_utterance():
    steps = [
        {"source_file": "1.mp4", "start": 10.0, "end": 20.0, "text": "第一句"},
        {"source_file": "1.mp4", "start": 20.3, "end": 28.0, "text": "紧接"},
    ]
    assert (
        _snap_start_to_utterance(
            steps,
            "1.mp4",
            21.0,
            lead_in_seconds=START_LEAD_IN_SECONDS,
            min_gap_seconds=MIN_START_GAP_SECONDS,
        )
        is None
    )


def test_short_rejects_overlapping_asr_instead_of_mid_line():
    """上一句 end 落入下一句时，短片不得 clamp 到句中。"""
    steps = [
        {"source_file": "1.mp4", "start": 10.0, "end": 21.0, "text": "第一句"},
        {"source_file": "1.mp4", "start": 20.0, "end": 28.0, "text": "重叠"},
    ]
    assert (
        _snap_start_to_utterance(
            steps,
            "1.mp4",
            21.0,
            lead_in_seconds=START_LEAD_IN_SECONDS,
            min_gap_seconds=MIN_START_GAP_SECONDS,
        )
        is None
    )


def test_short_start_not_flush_against_prev_end():
    """短片起点须晚于上一句 end + 字幕垫，不得贴着上句结束。"""
    steps = [
        {"source_file": "1.mp4", "start": 10.0, "end": 20.0, "text": "第一句"},
        {"source_file": "1.mp4", "start": 22.0, "end": 30.0, "text": "有空隙"},
    ]
    snapped = _snap_start_to_utterance(
        steps,
        "1.mp4",
        21.0,
        lead_in_seconds=START_LEAD_IN_SECONDS,
        min_gap_seconds=MIN_START_GAP_SECONDS,
    )
    assert snapped is not None
    assert snapped >= 20.0 + POST_UTTERANCE_PAD_SECONDS - 1e-9
    assert snapped <= 22.0 - MIN_BEFORE_SPEECH_SECONDS + 1e-9
    assert snapped == _expected_short_preferred(20.0, 22.0)


def test_short_half_second_gap_rejected():
    """0.5s 原始空隙不足以容纳字幕垫 + 句前缓冲。"""
    steps = [
        {"source_file": "1.mp4", "start": 10.0, "end": 20.0, "text": "第一句"},
        {"source_file": "1.mp4", "start": 20.5, "end": 28.0, "text": "半秒空隙"},
    ]
    assert (
        _snap_start_to_utterance(
            steps,
            "1.mp4",
            21.0,
            lead_in_seconds=START_LEAD_IN_SECONDS,
            min_gap_seconds=MIN_START_GAP_SECONDS,
        )
        is None
    )


def test_snap_start_before_first_keeps_lead_in():
    steps = [
        {"source_file": "1.mp4", "start": 8.0, "end": 12.0, "text": "开场"},
    ]
    assert _snap_start_to_utterance(steps, "1.mp4", 1.0) == round(
        max(0.0, 8.0 - START_LEAD_IN_SECONDS), 3
    )


def test_snap_start_ignores_other_episodes():
    steps = [
        {"source_file": "2.mp4", "start": 0.0, "end": 5.0, "text": "别集"},
        {"source_file": "1.mp4", "start": 40.0, "end": 50.0, "text": "本集"},
    ]
    assert _snap_start_to_utterance(steps, "1.mp4", 45.0) == round(
        40.0 - START_LEAD_IN_SECONDS, 3
    )


def test_snap_start_lead_in_zero_snaps_to_sentence_start():
    steps = [
        {"source_file": "1.mp4", "start": 10.0, "end": 20.0, "text": "第一句"},
        {"source_file": "1.mp4", "start": 22.0, "end": 30.0, "text": "第二句"},
    ]
    assert _snap_start_to_utterance(
        steps, "1.mp4", 15.5, lead_in_seconds=0
    ) == 10.0


def test_pick_short_start_fits_duration_by_moving_later():
    """句前缓冲过长导致超时长时，在窗内后移起点。"""
    steps = [
        {"source_file": "1.mp4", "start": 10.0, "end": 12.0, "text": "开场"},
        {"source_file": "1.mp4", "start": 20.0, "end": 140.0, "text": "长段"},
    ]
    cut_point = 134.4
    picked = _pick_short_start_for_duration(
        steps,
        "1.mp4",
        11.0,
        s_idx=0,
        l_idx=0,
        cut_point=cut_point,
        ordered_files=["1.mp4"],
        episode_end_times={"1.mp4": 200.0},
        min_dur=100,
        max_dur=115,
    )
    assert picked is not None
    assert 100 <= (cut_point - picked) <= 115
    assert picked >= 12.0 + POST_UTTERANCE_PAD_SECONDS - 1e-9
    assert picked <= 20.0 - MIN_BEFORE_SPEECH_SECONDS + 1e-9


def test_compress_script_includes_start_end():
    steps = [
        {"source_file": "1.mp4", "start": 1.2, "end": 3.8, "text": "你好"},
        {"source_file": "2.mp4", "start": 0.0, "end": 2.0, "text": "跳过"},
    ]
    out = _compress_script(steps, ["1.mp4"])
    assert "[1.mp4](1.2-3.8)你好" in out
    assert "2.mp4" not in out
