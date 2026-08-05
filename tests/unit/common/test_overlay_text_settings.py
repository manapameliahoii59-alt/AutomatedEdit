from app.common.overlay_text_settings import (
    DEFAULT_DISCLAIMER,
    DEFAULT_TITLE,
    build_drawtext_filter,
    build_overlay_drawtext_filters,
    clamp_font_key,
    clamp_overlay_style,
    escape_drawtext,
    position_for_orientation,
    resolve_overlay_text,
    set_position_for_orientation,
)


def test_clamp_overlay_style_defaults():
    style = clamp_overlay_style(None, DEFAULT_TITLE)
    assert style["text"] == "《{name}》"
    assert style["font"] == "msyh"
    assert style["fontsize"] == 22
    assert style["color"] == "#FFFFFF"
    assert style["opacity"] == 0.8
    assert style["portrait"] == {"x_pct": 4.0, "y_pct": 94.5}
    assert style["landscape"] == {"x_pct": 2.5, "y_pct": 90.0}


def test_clamp_migrates_flat_xy_to_portrait():
    style = clamp_overlay_style(
        {"text": "hi", "x_pct": 10, "y_pct": 80},
        DEFAULT_DISCLAIMER,
    )
    assert style["portrait"] == {"x_pct": 10.0, "y_pct": 80.0}
    # landscape 走默认
    assert style["landscape"] == {"x_pct": 2.5, "y_pct": 94.0}


def test_clamp_overlay_style_bounds():
    style = clamp_overlay_style(
        {
            "text": "hi",
            "font": "unknown",
            "fontsize": 999,
            "color": "ff0",
            "opacity": 2,
            "portrait": {"x_pct": -10, "y_pct": 200},
            "landscape": {"x_pct": 150, "y_pct": -5},
        },
        DEFAULT_DISCLAIMER,
    )
    assert style["font"] == "msyh"
    assert style["fontsize"] == 200
    assert style["color"] == "#FFFF00"
    assert style["opacity"] == 1.0
    assert style["portrait"] == {"x_pct": 0.0, "y_pct": 100.0}
    assert style["landscape"] == {"x_pct": 100.0, "y_pct": 0.0}


def test_clamp_font_key():
    assert clamp_font_key("simhei") == "simhei"
    assert clamp_font_key("SIMHEI.TTF") == "simhei"
    assert clamp_font_key("nope") == "msyh"


def test_resolve_overlay_text():
    assert resolve_overlay_text("《{name}》", "狂飙") == "《狂飙》"
    assert resolve_overlay_text("  ", "狂飙") == ""
    assert resolve_overlay_text("", "狂飙") == ""


def test_apply_text_layout_vertical():
    from app.common.overlay_text_settings import apply_text_layout

    assert apply_text_layout("剧名", "horizontal") == "剧名"
    assert apply_text_layout("剧名", "vertical") == "剧\n名"
    assert apply_text_layout("内容 虚构", "vertical") == "内\n容\n　\n虚\n构"
    assert apply_text_layout("《狂飙》", "horizontal") == "《狂飙》"
    assert apply_text_layout("《狂飙》", "vertical") == "︽\n狂\n飙\n︾"


def test_build_drawtext_vertical_uses_newlines():
    style = clamp_overlay_style(
        {
            "text": "AB",
            "layout": "vertical",
            "fontsize": 14,
            "color": "#FFFFFF",
            "opacity": 1.0,
            "portrait": {"x_pct": 5, "y_pct": 10},
            "landscape": {"x_pct": 5, "y_pct": 10},
        },
        DEFAULT_TITLE,
    )
    out = build_drawtext_filter(
        style, project_name="x", fontfile="msyh.ttc", orientation="portrait"
    )
    assert out is not None
    assert r"text='A\nB'" in out


def test_position_for_orientation_and_set():
    style = clamp_overlay_style(None, DEFAULT_TITLE)
    style = set_position_for_orientation(style, "landscape", 12, 88)
    assert position_for_orientation(style, "landscape") == {
        "x_pct": 12.0,
        "y_pct": 88.0,
    }
    assert position_for_orientation(style, "portrait")["x_pct"] == 4.0


def test_build_drawtext_filter_empty_skips():
    style = dict(DEFAULT_DISCLAIMER)
    style["text"] = ""
    assert build_drawtext_filter(style, project_name="测试") is None


def test_build_drawtext_uses_orientation_position():
    style = clamp_overlay_style(
        {
            "text": "《{name}》",
            "font": "msyh",
            "fontsize": 22,
            "color": "#FFFFFF",
            "opacity": 0.8,
            "portrait": {"x_pct": 10, "y_pct": 90},
            "landscape": {"x_pct": 20, "y_pct": 80},
        },
        DEFAULT_TITLE,
    )
    portrait = build_drawtext_filter(
        style, project_name="剧A", fontfile="msyh.ttc", orientation="portrait"
    )
    landscape = build_drawtext_filter(
        style, project_name="剧A", fontfile="msyh.ttc", orientation="landscape"
    )
    assert portrait is not None and landscape is not None
    assert "x=w*0.100000" in portrait and "y=h*0.900000" in portrait
    assert "x=w*0.200000" in landscape and "y=h*0.800000" in landscape


def test_build_overlay_filters_with_defaults(monkeypatch):
    class _Item:
        def __init__(self, value):
            self.value = value

    from app.common import config as config_mod

    monkeypatch.setattr(config_mod.cfg, "overlay_title_json", _Item(""))
    monkeypatch.setattr(config_mod.cfg, "overlay_disclaimer_json", _Item(""))
    filters = build_overlay_drawtext_filters("测试剧", horizontal=False)
    assert len(filters) == 2
    assert "《测试剧》" in filters[0]
    assert "内容纯属虚构" in filters[1]
    assert "x=w*0.040000" in filters[0]

    filters_h = build_overlay_drawtext_filters("测试剧", horizontal=True)
    assert "x=w*0.025000" in filters_h[0]


def test_build_overlay_filters_empty_both(monkeypatch):
    import json

    class _Item:
        def __init__(self, value):
            self.value = value

    from app.common import config as config_mod

    empty_title = dict(DEFAULT_TITLE)
    empty_title["text"] = ""
    empty_disc = dict(DEFAULT_DISCLAIMER)
    empty_disc["text"] = ""
    monkeypatch.setattr(
        config_mod.cfg, "overlay_title_json", _Item(json.dumps(empty_title))
    )
    monkeypatch.setattr(
        config_mod.cfg, "overlay_disclaimer_json", _Item(json.dumps(empty_disc))
    )
    assert build_overlay_drawtext_filters("测试剧") == []
