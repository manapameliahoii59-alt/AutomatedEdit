import datetime

from app.common.export_paths import (
    build_clip_export_filename,
    clamp_export_date_format,
    clamp_export_seq_format,
    format_export_date,
    format_export_sequence,
)

_WHEN = datetime.datetime(2026, 8, 19, 12, 0, 0)


def test_clamp_export_formats():
    assert clamp_export_date_format(None) == "md"
    assert clamp_export_date_format("ymd") == "ymd"
    assert clamp_export_date_format("weird") == "md"
    assert clamp_export_seq_format("") == "pad2"
    assert clamp_export_seq_format("plain") == "plain"
    assert clamp_export_seq_format("paren_pad2") == "paren_pad2"
    assert clamp_export_seq_format("pad9") == "pad2"


def test_format_export_date_and_sequence():
    assert format_export_date(_WHEN, "md") == "0819"
    assert format_export_date(_WHEN, "ymd") == "20260819"
    assert format_export_date(_WHEN, "ymd_dash") == "2026-08-19"
    assert format_export_date(_WHEN, "none") == ""
    assert format_export_sequence(1, "pad2") == "01"
    assert format_export_sequence(1, "pad3") == "001"
    assert format_export_sequence(12, "plain") == "12"
    assert format_export_sequence(1, "paren_pad2") == "(01)"
    assert format_export_sequence(2, "paren_pad2") == "(02)"
    assert format_export_sequence(3, "paren_plain") == "(3)"


def test_build_clip_export_filename_presets():
    kwargs = {"when": _WHEN, "tag": "阿飞", "date_format": "md", "seq_format": "pad2"}
    assert (
        build_clip_export_filename("狂飙", 1, **kwargs) == "狂飙-阿飞-0819-01"
    )
    assert (
        build_clip_export_filename(
            "狂飙", 1, when=_WHEN, tag="阿飞", date_format="ymd", seq_format="pad2"
        )
        == "狂飙-阿飞-20260819-01"
    )
    assert (
        build_clip_export_filename(
            "狂飙",
            1,
            when=_WHEN,
            tag="阿飞",
            date_format="ymd_dash",
            seq_format="pad3",
        )
        == "狂飙-阿飞-2026-08-19-001"
    )
    assert (
        build_clip_export_filename(
            "狂飙", 7, when=_WHEN, tag="阿飞", date_format="none", seq_format="plain"
        )
        == "狂飙-阿飞-7"
    )
    assert (
        build_clip_export_filename(
            "狂飙", 1, when=_WHEN, tag="阿飞", date_format="none", seq_format="paren_pad2"
        )
        == "狂飙-阿飞-(01)"
    )
    assert (
        build_clip_export_filename(
            "狂飙", 1, when=_WHEN, tag="", date_format="md", seq_format="pad2"
        )
        == "狂飙-0819-01"
    )


def test_build_clip_export_filename_reads_cfg(monkeypatch):
    class _Item:
        def __init__(self, value):
            self.value = value

    from app.common import config as config_mod

    monkeypatch.setattr(config_mod.cfg, "clip_export_name_tag", _Item("标识"))
    monkeypatch.setattr(config_mod.cfg, "clip_export_date_format", _Item("ymd"))
    monkeypatch.setattr(config_mod.cfg, "clip_export_seq_format", _Item("pad3"))
    name = build_clip_export_filename("剧", 2, when=_WHEN)
    assert name == "剧-标识-20260819-002"
