from app.common.overlay_text_settings import (
    DEFAULT_DISCLAIMER,
    DEFAULT_TITLE,
    build_drawtext_filter,
    build_drawtext_filters,
    build_overlay_drawtext_filters,
    clamp_font_key,
    clamp_overlay_style,
    clamp_text_effect,
    escape_drawtext,
    position_for_orientation,
    resolve_glow_color,
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
    assert style["effect"] == "none"
    assert style["glow_color"] == "#FFFFFF"
    assert style["portrait"]["x_pct"] == 4.0
    assert style["portrait"]["y_pct"] == 94.5
    assert style["portrait"]["fontsize"] == 22
    assert style["landscape"]["x_pct"] == 2.5
    assert style["landscape"]["y_pct"] == 90.0
    assert style["landscape"]["fontsize"] == 22


def test_clamp_legacy_style_defaults_effect():
    """旧配置缺 effect/glow_color 时回落到 none。"""
    style = clamp_overlay_style(
        {
            "text": "hi",
            "font": "msyh",
            "fontsize": 16,
            "color": "#FFFFFF",
            "opacity": 1.0,
            "portrait": {"x_pct": 5, "y_pct": 10},
            "landscape": {"x_pct": 5, "y_pct": 10},
        },
        DEFAULT_TITLE,
    )
    assert style["effect"] == "none"
    assert style["glow_color"] == "#FFFFFF"


def test_clamp_text_effect_and_glow_color():
    assert clamp_text_effect("neon") == "neon"
    assert clamp_text_effect("NEON") == "neon"
    assert clamp_text_effect("pink_mood") == "pink_mood"
    assert clamp_text_effect("weird") == "none"
    assert clamp_text_effect(None) == "none"

    neon = clamp_overlay_style(
        {"effect": "neon", "glow_color": ""},
        DEFAULT_TITLE,
    )
    assert neon["effect"] == "neon"
    assert resolve_glow_color(neon) == "#00E5FF"

    guochao = clamp_overlay_style(
        {"effect": "guochao", "glow_color": "#ff00aa"},
        DEFAULT_TITLE,
    )
    assert resolve_glow_color(guochao) == "#FF00AA"


def test_build_drawtext_glow_layers():
    style = clamp_overlay_style(
        {
            "text": "A",
            "fontsize": 20,
            "color": "#FFFFFF",
            "opacity": 1.0,
            "effect": "glow",
            "glow_color": "#00FF88",
            "portrait": {"x_pct": 5, "y_pct": 10},
            "landscape": {"x_pct": 5, "y_pct": 10},
        },
        DEFAULT_TITLE,
    )
    parts = build_drawtext_filters(
        style, project_name="x", fontfile="msyh.ttc", orientation="portrait"
    )
    # 中心雾 + 4 圈×8 向 + 正文；辉光层无彩色硬描边，正文有细黑边
    assert len(parts) == 1 + 4 * 8 + 1
    assert all("borderw=" not in p for p in parts[:-1])
    assert "borderw=" in parts[-1]
    assert "bordercolor=000000@" in parts[-1]
    assert any("fontcolor=00FF88@" in p for p in parts[:-1])
    assert "fontcolor=FFFFFF@1.0" in parts[-1] or "fontcolor=FFFFFF@1" in parts[-1]


def test_build_drawtext_neon_and_guochao():
    neon = clamp_overlay_style(
        {
            "text": "霓",
            "effect": "neon",
            "glow_color": "#00E5FF",
            "portrait": {"x_pct": 1, "y_pct": 1},
            "landscape": {"x_pct": 1, "y_pct": 1},
        },
        DEFAULT_TITLE,
    )
    neon_parts = build_drawtext_filters(
        neon, project_name="x", fontfile="msyh.ttc"
    )
    assert len(neon_parts) == 1 + 4 * 8 + 1
    assert any("fontcolor=00E5FF@" in p for p in neon_parts[:-1])
    assert "borderw=" in neon_parts[-1]

    guochao = clamp_overlay_style(
        {
            "text": "痛",
            "font": "stxingka",
            "effect": "guochao",
            "glow_color": "#FF2D6A",
            "portrait": {"x_pct": 1, "y_pct": 1},
            "landscape": {"x_pct": 1, "y_pct": 1},
        },
        DEFAULT_TITLE,
    )
    gc_parts = build_drawtext_filters(
        guochao, project_name="x", fontfile="STXINGKA.TTF"
    )
    assert len(gc_parts) == 1 + 4 * 8 + 1
    assert "shadowx=2" in gc_parts[-1]
    assert "shadowcolor=black@0.45" in gc_parts[-1]
    assert any("fontcolor=FF2D6A@" in p for p in gc_parts[:-1])


def test_build_drawtext_pink_mood_and_outline():
    pink = clamp_overlay_style(
        {
            "text": "粉",
            "effect": "pink_mood",
            "glow_color": "",
            "portrait": {"x_pct": 1, "y_pct": 1},
            "landscape": {"x_pct": 1, "y_pct": 1},
        },
        DEFAULT_TITLE,
    )
    assert pink["glow_color"] == "#FF4FA3"
    pink_parts = build_drawtext_filters(
        pink, project_name="x", fontfile="msyh.ttc"
    )
    assert len(pink_parts) == 1 + 4 * 8 + 1
    assert any("fontcolor=FF4FA3@" in p for p in pink_parts[:-1])

    outline = clamp_overlay_style(
        {
            "text": "边",
            "effect": "outline",
            "portrait": {"x_pct": 1, "y_pct": 1},
            "landscape": {"x_pct": 1, "y_pct": 1},
        },
        DEFAULT_TITLE,
    )
    outline_parts = build_drawtext_filters(
        outline, project_name="x", fontfile="msyh.ttc"
    )
    assert len(outline_parts) == 1
    assert "borderw=" in outline_parts[0]
    assert "bordercolor=000000@" in outline_parts[0]


def test_more_drama_styles_and_fonts():
    from app.common.overlay_text_settings import (
        EFFECT_CHOICES,
        FONT_CHOICES,
        available_font_choices,
        clamp_font_key,
    )

    assert len(EFFECT_CHOICES) >= 20
    assert len(FONT_CHOICES) >= 18
    assert clamp_font_key("sthupo") == "sthupo"
    assert clamp_font_key("simyou") == "simyou"
    assert clamp_text_effect("manga_yellow") == "manga_yellow"
    assert clamp_text_effect("purple_dream") == "purple_dream"
    # 本机至少能列出核心字体
    keys = {k for k, _l, _f in available_font_choices()}
    assert {"msyh", "simhei", "simkai"} <= keys

    manga = clamp_overlay_style(
        {"text": "漫", "effect": "manga_yellow", "glow_color": ""},
        DEFAULT_TITLE,
    )
    assert manga["glow_color"] == "#FFD400"
    parts = build_drawtext_filters(manga, project_name="x", fontfile="msyh.ttc")
    assert "borderw=" in parts[-1]



def test_clamp_migrates_flat_xy_to_portrait():
    style = clamp_overlay_style(
        {"text": "hi", "x_pct": 10, "y_pct": 80},
        DEFAULT_DISCLAIMER,
    )
    assert style["portrait"]["x_pct"] == 10.0
    assert style["portrait"]["y_pct"] == 80.0
    assert style["portrait"]["fontsize"] == 14
    # landscape 走默认位置，顶层样式迁入
    assert style["landscape"]["x_pct"] == 2.5
    assert style["landscape"]["y_pct"] == 94.0
    assert style["landscape"]["fontsize"] == 14


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
    assert style["fontsize"] == 90
    assert style["color"] == "#FFFF00"
    assert style["opacity"] == 1.0
    assert style["portrait"]["x_pct"] == 0.0
    assert style["portrait"]["y_pct"] == 100.0
    assert style["portrait"]["fontsize"] == 90
    assert style["landscape"]["x_pct"] == 100.0
    assert style["landscape"]["y_pct"] == 0.0
    assert style["landscape"]["fontsize"] == 90


def test_orient_styles_independent():
    """横屏/竖屏字体参数互不影响。"""
    from app.common.overlay_text_settings import (
        style_for_orientation,
        update_orient_style,
    )

    style = clamp_overlay_style(None, DEFAULT_TITLE)
    style = update_orient_style(
        style,
        "portrait",
        {"font": "simhei", "fontsize": 40, "effect": "neon"},
        defaults=DEFAULT_TITLE,
    )
    style = update_orient_style(
        style,
        "landscape",
        {"font": "simkai", "fontsize": 18, "effect": "outline"},
        defaults=DEFAULT_TITLE,
    )
    p = style_for_orientation(style, "portrait", defaults=DEFAULT_TITLE)
    l = style_for_orientation(style, "landscape", defaults=DEFAULT_TITLE)
    assert p["font"] == "simhei"
    assert p["fontsize"] == 40
    assert p["effect"] == "neon"
    assert l["font"] == "simkai"
    assert l["fontsize"] == 18
    assert l["effect"] == "outline"

    # 旧仅坐标桶：顶层样式迁入两侧，之后仍可独立改
    legacy = clamp_overlay_style(
        {
            "text": "《{name}》",
            "font": "simhei",
            "fontsize": 36,
            "color": "#FF0000",
            "opacity": 0.9,
            "effect": "glow",
            "portrait": {"x_pct": 1, "y_pct": 2},
            "landscape": {"x_pct": 3, "y_pct": 4},
        },
        DEFAULT_TITLE,
    )
    assert legacy["portrait"]["font"] == "simhei"
    assert legacy["portrait"]["fontsize"] == 36
    assert legacy["landscape"]["fontsize"] == 36
    assert legacy["portrait"]["x_pct"] == 1.0
    assert legacy["landscape"]["x_pct"] == 3.0


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


def test_build_drawtext_vertical_uses_separate_filters():
    from app.common.overlay_text_settings import build_drawtext_filters

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
    parts = build_drawtext_filters(
        style, project_name="x", fontfile="msyh.ttc", orientation="portrait"
    )
    assert len(parts) == 2
    assert "text='A'" in parts[0]
    assert "text='B'" in parts[1]
    assert "y=h*0.100000" in parts[0]
    assert "y=h*0.100000+1*(14+" in parts[1]
    # 绝不能把换行逃成字母 n
    joined = ",".join(parts)
    assert r"\n" not in joined
    assert "text='AnB'" not in joined
    assert "text='A\\nB'" not in joined


def test_escape_drawtext_single_line():
    from app.common.overlay_text_settings import escape_drawtext

    assert escape_drawtext("a\nb") == "ab"
    assert escape_drawtext("a:b") == r"a\:b"
    assert escape_drawtext("100%") == "100%%"


def test_position_for_orientation_and_set():
    style = clamp_overlay_style(None, DEFAULT_TITLE)
    style = set_position_for_orientation(style, "landscape", 12, 88)
    land = position_for_orientation(style, "landscape")
    assert land["x_pct"] == 12.0
    assert land["y_pct"] == 88.0
    assert land["fontsize"] == 22
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
    monkeypatch.setattr(config_mod.cfg, "overlay_text_library_json", _Item(""))

    def _fake_set(item, value):
        item.value = value

    monkeypatch.setattr("qfluentwidgets.qconfig.set", _fake_set)
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
    from app.common.overlay_text_settings import (
        DEFAULT_OVERLAY_GROUP_ID,
        make_overlay_group,
        save_overlay_library_to_cfg,
    )

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
    lib_item = _Item("")
    monkeypatch.setattr(config_mod.cfg, "overlay_text_library_json", lib_item)

    def _fake_set(item, value):
        item.value = value

    monkeypatch.setattr("qfluentwidgets.qconfig.set", _fake_set)
    save_overlay_library_to_cfg(
        {
            "selected_id": DEFAULT_OVERLAY_GROUP_ID,
            "groups": [
                make_overlay_group(
                    name="默认",
                    title=empty_title,
                    disclaimer=empty_disc,
                    group_id=DEFAULT_OVERLAY_GROUP_ID,
                )
            ],
        }
    )
    assert build_overlay_drawtext_filters("测试剧") == []


def test_apply_overlay_skips_server_defaults_when_local_exists(monkeypatch):
    """服务端空配置会填默认叠字；本地已有自定义时不应被覆盖。"""
    import json

    from app.common.overlay_text_settings import (
        apply_overlay_from_clip_edit_dict,
        default_overlay_title,
    )

    class _Item:
        def __init__(self, value):
            self.value = value

    from app.common import config as config_mod

    custom = dict(default_overlay_title())
    custom["fontsize"] = 48
    custom["layout"] = "vertical"
    local_title = _Item(json.dumps(custom, ensure_ascii=False))
    local_disc = _Item(json.dumps(DEFAULT_DISCLAIMER, ensure_ascii=False))
    local_tag = _Item("old")
    monkeypatch.setattr(config_mod.cfg, "overlay_title_json", local_title)
    monkeypatch.setattr(config_mod.cfg, "overlay_disclaimer_json", local_disc)
    monkeypatch.setattr(config_mod.cfg, "overlay_text_library_json", _Item(""))
    monkeypatch.setattr(config_mod.cfg, "clip_export_name_tag", local_tag)

    sets: list[tuple] = []

    def _fake_set(item, value):
        sets.append((item, value))
        item.value = value

    monkeypatch.setattr("qfluentwidgets.qconfig.set", _fake_set)

    apply_overlay_from_clip_edit_dict(
        {
            "export_name_tag": "new",
            "overlay_title": dict(DEFAULT_TITLE),
            "overlay_disclaimer": dict(DEFAULT_DISCLAIMER),
        }
    )

    # 叠字保持本地；文件名标识仍同步
    assert local_title.value == json.dumps(custom, ensure_ascii=False)
    assert any(item is local_tag and value == "new" for item, value in sets)


def test_apply_overlay_accepts_non_default_server_style(monkeypatch):
    import json

    from app.common.overlay_text_settings import apply_overlay_from_clip_edit_dict

    class _Item:
        def __init__(self, value):
            self.value = value

    from app.common import config as config_mod

    local_title = _Item(json.dumps(DEFAULT_TITLE, ensure_ascii=False))
    local_disc = _Item("")
    local_lib = _Item("")
    monkeypatch.setattr(config_mod.cfg, "overlay_title_json", local_title)
    monkeypatch.setattr(config_mod.cfg, "overlay_disclaimer_json", local_disc)
    monkeypatch.setattr(config_mod.cfg, "overlay_text_library_json", local_lib)
    monkeypatch.setattr(config_mod.cfg, "clip_export_name_tag", _Item(""))

    def _fake_set(item, value):
        item.value = value

    monkeypatch.setattr("qfluentwidgets.qconfig.set", _fake_set)

    # 旧形态：顶层样式 + 仅坐标的横竖桶
    server_title = {
        "text": "《{name}》",
        "font": "msyh",
        "fontsize": 40,
        "color": "#FFFFFF",
        "opacity": 0.8,
        "layout": "horizontal",
        "effect": "none",
        "glow_color": "#FFFFFF",
        "portrait": {"x_pct": 4.0, "y_pct": 94.5},
        "landscape": {"x_pct": 2.5, "y_pct": 90.0},
    }
    apply_overlay_from_clip_edit_dict({"overlay_title": server_title})
    # 旧字段迁入 library 默认组
    from app.common.overlay_text_settings import load_overlay_library_from_cfg

    lib = load_overlay_library_from_cfg()
    assert lib["groups"][0]["title"]["fontsize"] == 40
    assert lib["groups"][0]["title"]["portrait"]["fontsize"] == 40


def test_overlay_library_migrate_and_active_group(monkeypatch):
    import json

    from app.common.overlay_text_settings import (
        DEFAULT_OVERLAY_GROUP_ID,
        delete_overlay_group,
        load_overlay_library_from_cfg,
        make_overlay_group,
        resolve_active_overlay_group,
        save_overlay_library_to_cfg,
        set_selected_overlay_id,
        upsert_overlay_group,
    )

    class _Item:
        def __init__(self, value):
            self.value = value

    from app.common import config as config_mod

    # 旧配置：顶层字号 + 横竖仅坐标
    legacy_title = {
        "text": "《{name}》",
        "font": "msyh",
        "fontsize": 33,
        "color": "#FFFFFF",
        "opacity": 0.8,
        "layout": "horizontal",
        "effect": "none",
        "glow_color": "#FFFFFF",
        "portrait": {"x_pct": 4.0, "y_pct": 94.5},
        "landscape": {"x_pct": 2.5, "y_pct": 90.0},
    }
    title_item = _Item(json.dumps(legacy_title, ensure_ascii=False))
    disc_item = _Item(json.dumps(DEFAULT_DISCLAIMER, ensure_ascii=False))
    lib_item = _Item("")
    monkeypatch.setattr(config_mod.cfg, "overlay_title_json", title_item)
    monkeypatch.setattr(config_mod.cfg, "overlay_disclaimer_json", disc_item)
    monkeypatch.setattr(config_mod.cfg, "overlay_text_library_json", lib_item)

    def _fake_set(item, value):
        item.value = value

    monkeypatch.setattr("qfluentwidgets.qconfig.set", _fake_set)

    lib = load_overlay_library_from_cfg()
    assert len(lib["groups"]) >= 1
    assert lib["groups"][0]["id"] == DEFAULT_OVERLAY_GROUP_ID
    assert lib["groups"][0]["title"]["fontsize"] == 33
    assert lib["groups"][0]["title"]["portrait"]["fontsize"] == 33
    assert lib_item.value  # 已落盘

    # 未勾选 → 回退默认组
    set_selected_overlay_id("")
    active = resolve_active_overlay_group()
    assert active["id"] == DEFAULT_OVERLAY_GROUP_ID

    extra = make_overlay_group(name="粉雾标题", title={"fontsize": 48, "text": "《{name}》"})
    upsert_overlay_group(extra)
    set_selected_overlay_id(extra["id"])
    active2 = resolve_active_overlay_group()
    assert active2["id"] == extra["id"]
    assert active2["name"] == "粉雾标题"

    # 默认组不可删
    before = len(load_overlay_library_from_cfg()["groups"])
    delete_overlay_group(DEFAULT_OVERLAY_GROUP_ID)
    assert len(load_overlay_library_from_cfg()["groups"]) == before

    delete_overlay_group(extra["id"])
    lib3 = load_overlay_library_from_cfg()
    assert all(g["id"] != extra["id"] for g in lib3["groups"])
    # 勾选被清掉后回退默认
    assert resolve_active_overlay_group()["id"] == DEFAULT_OVERLAY_GROUP_ID


def test_build_overlay_filters_uses_selected_group(monkeypatch):
    import json

    from app.common.overlay_text_settings import (
        build_overlay_drawtext_filters,
        make_overlay_group,
        save_overlay_library_to_cfg,
    )

    class _Item:
        def __init__(self, value):
            self.value = value

    from app.common import config as config_mod

    monkeypatch.setattr(config_mod.cfg, "overlay_title_json", _Item(""))
    monkeypatch.setattr(config_mod.cfg, "overlay_disclaimer_json", _Item(""))
    lib_item = _Item("")
    monkeypatch.setattr(config_mod.cfg, "overlay_text_library_json", lib_item)

    def _fake_set(item, value):
        item.value = value

    monkeypatch.setattr("qfluentwidgets.qconfig.set", _fake_set)

    g = make_overlay_group(
        name="测试组",
        title={
            "text": "《{name}》专属",
            "fontsize": 22,
            "color": "#FFFFFF",
            "opacity": 1.0,
            "portrait": {"x_pct": 4, "y_pct": 90},
            "landscape": {"x_pct": 4, "y_pct": 90},
        },
        disclaimer={"text": ""},
    )
    save_overlay_library_to_cfg({"selected_id": g["id"], "groups": [g]})
    filters = build_overlay_drawtext_filters("测试剧")
    assert any("《测试剧》专属" in f for f in filters)
