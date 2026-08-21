"""综艺花字 Pillow 预渲与 overlay plan 冒烟测试。"""

from __future__ import annotations

import os

import pytest

from app.common.huazi_render import render_huazi_image, render_huazi_png_file
from app.common.huazi_styles import HUAZI_STYLE_IDS, is_huazi_effect
from app.common.overlay_text_settings import (
    build_drawtext_filters,
    build_overlay_plan,
    clamp_text_effect,
)


def _system_font() -> str | None:
    windir = os.environ.get("WINDIR", "C:/Windows")
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "arial.ttf"):
        path = os.path.join(windir, "Fonts", name)
        if os.path.isfile(path):
            return path
    return None


@pytest.fixture(scope="module")
def font_path():
    path = _system_font()
    if not path:
        pytest.skip("系统字体不可用")
    return path


def test_huazi_style_ids_registered():
    assert len(HUAZI_STYLE_IDS) >= 12
    for sid in HUAZI_STYLE_IDS:
        assert is_huazi_effect(sid)
        assert clamp_text_effect(sid) == sid


def test_render_huazi_image_smoke(font_path):
    img = render_huazi_image(
        "测试花字",
        "hz_sticker_pink",
        font_path=font_path,
        fontsize=36,
        opacity=1.0,
    )
    assert img.mode == "RGBA"
    assert img.width > 10
    assert img.height > 10
    # 应有非透明像素
    extrema = img.getextrema()
    assert extrema[3][1] > 0


def test_render_huazi_png_file_cached(font_path, tmp_path):
    path1 = render_huazi_png_file(
        "缓存测",
        "hz_gold_3d",
        font_path=font_path,
        fontsize=40,
        cache_dir=str(tmp_path),
    )
    path2 = render_huazi_png_file(
        "缓存测",
        "hz_gold_3d",
        font_path=font_path,
        fontsize=40,
        cache_dir=str(tmp_path),
    )
    assert path1 == path2
    assert os.path.isfile(path1)
    assert os.path.getsize(path1) > 100


def test_all_huazi_styles_render(font_path, tmp_path):
    for sid in sorted(HUAZI_STYLE_IDS):
        path = render_huazi_png_file(
            "样",
            sid,
            font_path=font_path,
            fontsize=28,
            cache_dir=str(tmp_path),
        )
        assert os.path.isfile(path), sid


def test_huazi_skips_drawtext():
    style = {
        "text": "《{name}》",
        "font": "msyh",
        "fontsize": 22,
        "color": "#FFFFFF",
        "opacity": 1.0,
        "layout": "horizontal",
        "effect": "hz_neon_cyan",
        "glow_color": "#FFFFFF",
        "portrait": {"x_pct": 10.0, "y_pct": 20.0},
        "landscape": {"x_pct": 10.0, "y_pct": 20.0},
    }
    assert build_drawtext_filters(style, project_name="剧", fontfile="x.ttf") == []


def test_build_overlay_plan_huazi_image(monkeypatch, font_path, tmp_path):
    title = {
        "text": "《{name}》",
        "font": "msyh",
        "fontsize": 24,
        "color": "#FFFFFF",
        "opacity": 1.0,
        "layout": "horizontal",
        "effect": "hz_sticker_pink",
        "glow_color": "#FFFFFF",
        "portrait": {"x_pct": 5.0, "y_pct": 80.0},
        "landscape": {"x_pct": 5.0, "y_pct": 80.0},
    }
    disc = {
        "text": "",
        "font": "msyh",
        "fontsize": 14,
        "color": "#FFFFFF",
        "opacity": 0.6,
        "layout": "horizontal",
        "effect": "none",
        "glow_color": "#FFFFFF",
        "portrait": {"x_pct": 4.0, "y_pct": 94.0},
        "landscape": {"x_pct": 4.0, "y_pct": 94.0},
    }
    monkeypatch.setattr(
        "app.common.overlay_text_settings.load_overlay_title_from_cfg",
        lambda: title,
    )
    monkeypatch.setattr(
        "app.common.overlay_text_settings.load_overlay_disclaimer_from_cfg",
        lambda: disc,
    )
    monkeypatch.setattr(
        "app.common.overlay_text_settings.prepare_font_file",
        lambda *_a, **_k: font_path,
    )
    monkeypatch.setattr(
        "app.common.overlay_text_settings.overlay_text_disabled_from_cfg",
        lambda: False,
    )

    plan = build_overlay_plan("测剧", horizontal=False, cache_dir=str(tmp_path))
    assert plan["drawtext_filters"] == []
    assert len(plan["image_overlays"]) == 1
    spec = plan["image_overlays"][0]
    assert os.path.isfile(spec["path"])
    assert "W*0.050000" in spec["x_expr"]
    assert "H*0.800000" in spec["y_expr"]
