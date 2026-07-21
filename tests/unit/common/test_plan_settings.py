from app.common.plan_settings import (
    clamp_clip_count,
    clamp_max_duration_seconds,
    split_ab_counts,
)


def test_clamp_clip_count():
    assert clamp_clip_count(10) == 10
    assert clamp_clip_count(3) == 5
    assert clamp_clip_count(20) == 15
    assert clamp_clip_count(None) == 15


def test_clamp_max_duration():
    assert clamp_max_duration_seconds(300) == 300
    assert clamp_max_duration_seconds(720) == 720
    assert clamp_max_duration_seconds(60) == 300
    assert clamp_max_duration_seconds(1200) == 900


def test_split_ab_ratio():
    assert split_ab_counts(15) == (6, 9)
    assert split_ab_counts(10) == (4, 6)
    assert split_ab_counts(5) == (2, 3)
    for n in range(5, 16):
        a, b = split_ab_counts(n)
        assert a + b == n
        assert a >= 1 and b >= 1
