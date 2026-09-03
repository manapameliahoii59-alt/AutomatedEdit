import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.services.plan_director import (
    MIN_BEFORE_SPEECH_SECONDS,
    POST_CUT_PAD_SECONDS,
    _compute_clip_duration,
    _cut_point_after,
    _find_cut_index,
    _normalize_short_ends,
    _resolve_cut_span,
)


def _steps():
    return [
        {"source_file": "1.mp4", "start": 10.0, "end": 12.0, "text": "开场垫"},
        {"source_file": "1.mp4", "start": 100.0, "end": 110.0, "text": "你不要再过来了"},
        {"source_file": "1.mp4", "start": 110.5, "end": 118.0, "text": "我真的会喊人"},
        {"source_file": "1.mp4", "start": 200.0, "end": 210.0, "text": "尾声台词"},
        {"source_file": "2.mp4", "start": 10.0, "end": 20.0, "text": "甲段台词"},
        {"source_file": "2.mp4", "start": 20.3, "end": 35.0, "text": "紧接下一句"},
    ]


def test_resolve_cut_span_across_segments():
    """ASR 拆句后引用横跨两段：末覆盖段才是句尾。"""
    steps = _steps()
    texts = [s["text"] for s in steps]
    ct = "你不要再过来了我真的会喊人"
    c_idx = _find_cut_index(steps, ct, texts)
    assert c_idx in (1, 2)
    assert _resolve_cut_span(steps, c_idx, ct, step_texts=texts) == 2


def test_resolve_cut_span_single_segment_unchanged():
    """引用完整落在单段内：不跨段。"""
    steps = _steps()
    texts = [s["text"] for s in steps]
    c_idx = _find_cut_index(steps, "尾声台词", texts)
    assert c_idx == 3
    assert _resolve_cut_span(steps, 3, "尾声台词", step_texts=texts) == 3


def test_resolve_cut_span_discontinuous_quote_conservative():
    """引用跳过中间句（不连续）：保守回退，不跨段。"""
    steps = _steps()
    texts = [s["text"] for s in steps]
    ct = "你不要再过来了尾声台词"
    c_idx = _find_cut_index(steps, ct, texts)
    assert c_idx in (1, 3)
    assert _resolve_cut_span(steps, c_idx, ct, step_texts=texts) == c_idx


def test_cut_point_after_clamped_by_next_utterance():
    """下一句 20.3s 开始（间隙 0.3s）：尾垫被钳制到句首前 0.3s。"""
    steps = _steps()
    # index 4 = 2.mp4 "甲段台词" end=20.0，下一句 start=20.3
    assert _cut_point_after(steps, 4) == round(
        min(20.0 + POST_CUT_PAD_SECONDS, 20.3 - MIN_BEFORE_SPEECH_SECONDS), 3
    )


def test_cut_point_after_overlap_floor():
    """下一句 20.05s 开始（几乎无缝）：不得早于台词结束 + 0.1s。"""
    steps = [
        {"source_file": "2.mp4", "start": 10.0, "end": 20.0, "text": "甲段台词"},
        {"source_file": "2.mp4", "start": 20.05, "end": 30.0, "text": "贴死下一句"},
    ]
    assert _cut_point_after(steps, 0) == 20.1


def test_cut_point_after_no_next_utterance():
    """无下一句：直接加尾垫。"""
    steps = _steps()
    # index 3 = 1.mp4 "尾声台词" end=210.0，1.mp4 无更晚台词
    assert _cut_point_after(steps, 3) == 210.0 + POST_CUT_PAD_SECONDS


def test_normalize_short_ends_uses_last_span_segment():
    """_normalize_short_ends 集成：跨段引用 → cut_point 按末段计算。"""
    steps = _steps()
    ends = [{"le": "1.mp4", "ct": "你不要再过来了我真的会喊人", "hook": "钩子"}]
    out = _normalize_short_ends(
        ends,
        steps=steps,
        step_texts=[s["text"] for s in steps],
        ordered_files=["1.mp4", "2.mp4"],
    )
    assert len(out) == 1
    assert out[0]["phys_end"] == 118.0
    assert out[0]["cut_point"] == 118.5


def test_compute_clip_duration_matches_new_pad():
    """时长反推物理终点用同一尾垫常量，保持一致。"""
    # 同集：cut - start
    assert (
        _compute_clip_duration(0, 0, 100.0, 150.5, ["1.mp4"], {"1.mp4": 300.0})
        == 50.5
    )
    # 跨集：首集剩余 + (cut - 尾垫)
    assert (
        _compute_clip_duration(
            0, 1, 100.0, 150.5, ["1.mp4", "2.mp4"], {"1.mp4": 200.0}
        )
        == 100.0 + (150.5 - POST_CUT_PAD_SECONDS)
    )
