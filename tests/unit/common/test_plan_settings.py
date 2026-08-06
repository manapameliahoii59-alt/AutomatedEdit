from app.common.plan_settings import (
    PLAN_MODE_LONG,
    PLAN_MODE_SHORT,
    SHORT_MIN_DURATION_SECONDS,
    MIN_DURATION_SECONDS,
    clamp_clip_count,
    clamp_global_speed,
    clamp_max_duration_seconds,
    clamp_plan_mode,
    clamp_short_max_duration_seconds,
    resolve_active_plan_params,
    short_max_duration_minutes_from_seconds,
    short_max_duration_seconds_from_minutes,
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


def test_clamp_short_max_duration():
    assert clamp_short_max_duration_seconds(120) == 120
    assert clamp_short_max_duration_seconds(300) == 300
    assert clamp_short_max_duration_seconds(60) == 120
    assert clamp_short_max_duration_seconds(600) == 300


def test_short_max_duration_minutes_roundtrip():
    assert short_max_duration_minutes_from_seconds(300) == 5
    assert short_max_duration_seconds_from_minutes(2) == 120
    assert short_max_duration_seconds_from_minutes(5) == 300


def test_clamp_plan_mode():
    assert clamp_plan_mode("short") == PLAN_MODE_SHORT
    assert clamp_plan_mode("SHORT") == PLAN_MODE_SHORT
    assert clamp_plan_mode("long") == PLAN_MODE_LONG
    assert clamp_plan_mode(None) == PLAN_MODE_LONG
    assert clamp_plan_mode("other") == PLAN_MODE_LONG


def test_split_ab_ratio():
    assert split_ab_counts(15) == (6, 9)
    assert split_ab_counts(10) == (4, 6)
    assert split_ab_counts(5) == (2, 3)
    for n in range(5, 16):
        a, b = split_ab_counts(n)
        assert a + b == n
        assert a >= 1 and b >= 1


def test_clamp_global_speed():
    assert clamp_global_speed(1.15) == 1.15
    assert clamp_global_speed(1.0) == 1.0
    assert clamp_global_speed(1.5) == 1.5
    assert clamp_global_speed(0.5) == 1.0
    assert clamp_global_speed(2.0) == 1.5
    assert clamp_global_speed(None) == 1.15
    assert clamp_global_speed("bad") == 1.15


def test_resolve_active_plan_params_long(monkeypatch):
    from app.common import config as config_mod

    class _Item:
        def __init__(self, value):
            self.value = value

    monkeypatch.setattr(config_mod.cfg, "plan_mode", _Item("long"))
    monkeypatch.setattr(config_mod.cfg, "plan_clip_count", _Item(10))
    monkeypatch.setattr(config_mod.cfg, "plan_max_duration_sec", _Item(600))
    monkeypatch.setattr(config_mod.cfg, "plan_short_clip_count", _Item(8))
    monkeypatch.setattr(config_mod.cfg, "plan_short_max_duration_sec", _Item(180))
    monkeypatch.setattr(config_mod.cfg, "plan_global_speed", _Item(1.2))

    params = resolve_active_plan_params()
    assert params["mode"] == PLAN_MODE_LONG
    assert params["clip_count"] == 10
    assert params["min_duration_sec"] == MIN_DURATION_SECONDS
    assert params["max_duration_sec"] == 600
    assert params["split_ab"] is True
    assert params["global_speed"] == 1.2


def test_resolve_active_plan_params_short(monkeypatch):
    from app.common import config as config_mod

    class _Item:
        def __init__(self, value):
            self.value = value

    monkeypatch.setattr(config_mod.cfg, "plan_mode", _Item("short"))
    monkeypatch.setattr(config_mod.cfg, "plan_clip_count", _Item(10))
    monkeypatch.setattr(config_mod.cfg, "plan_max_duration_sec", _Item(600))
    monkeypatch.setattr(config_mod.cfg, "plan_short_clip_count", _Item(8))
    monkeypatch.setattr(config_mod.cfg, "plan_short_max_duration_sec", _Item(180))
    monkeypatch.setattr(config_mod.cfg, "plan_global_speed", _Item(1.0))

    params = resolve_active_plan_params()
    assert params["mode"] == PLAN_MODE_SHORT
    assert params["clip_count"] == 8
    assert params["min_duration_sec"] == SHORT_MIN_DURATION_SECONDS
    assert params["max_duration_sec"] == 180
    assert params["split_ab"] is False
    assert params["global_speed"] == 1.0
