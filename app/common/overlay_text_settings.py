"""渲染画面叠字（剧名 / 提示）设置：默认值、clamp、drawtext 生成、cfg 读写。"""

from __future__ import annotations

import json
import math
import os
import shutil
import uuid
from typing import Any, Literal, TypedDict

Orientation = Literal["portrait", "landscape"]
TextLayout = Literal["horizontal", "vertical"]
# 具体取值见 _EFFECT_STYLES；未知 id 会 clamp 为 none
TextEffect = str

# 字体 key -> (显示名, Windows Fonts 文件名)
# 仅本机存在的会出现在下拉（核心字体始终保留）
FONT_CHOICES: tuple[tuple[str, str, str], ...] = (
    ("msyh", "微软雅黑", "msyh.ttc"),
    ("msyhbd", "微软雅黑粗体", "msyhbd.ttc"),
    ("msyhl", "微软雅黑细体", "msyhl.ttc"),
    ("simhei", "黑体", "simhei.ttf"),
    ("simsun", "宋体", "simsun.ttc"),
    ("simsunb", "粗宋", "simsunb.ttf"),
    ("simkai", "楷体", "simkai.ttf"),
    ("simfang", "仿宋", "simfang.ttf"),
    ("simli", "隶书", "SIMLI.TTF"),
    ("simyou", "幼圆", "SIMYOU.TTF"),
    ("stxingka", "华文行楷", "STXINGKA.TTF"),
    ("stxinwei", "华文新魏", "STXINWEI.TTF"),
    ("stkaiti", "华文楷体", "STKAITI.TTF"),
    ("stliti", "华文隶书", "STLITI.TTF"),
    ("sthupo", "华文琥珀", "STHUPO.TTF"),
    ("stcaiyun", "华文彩云", "STCAIYUN.TTF"),
    ("stxihei", "华文细黑", "STXIHEI.TTF"),
    ("stzhongs", "华文中宋", "STZHONGS.TTF"),
    ("stsong", "华文宋体", "STSONG.TTF"),
    ("stfangso", "华文仿宋", "STFANGSO.TTF"),
    ("fzstk", "方正舒体", "FZSTK.TTF"),
    ("fzytk", "方正姚体", "FZYTK.TTF"),
)

_FONT_BY_KEY = {k: (label, filename) for k, label, filename in FONT_CHOICES}
DEFAULT_FONT = "msyh"
_CORE_FONTS = {"msyh", "msyhbd", "simhei", "simsun", "simkai"}
_BRUSH_FONTS = ("stxingka", "fzstk", "fzytk", "stxinwei", "sthupo", "simkai")
_BOLD_FONTS = ("msyhbd", "simhei", "stzhongs", "sthupo")
_SOFT_FONTS = ("simyou", "stcaiyun", "msyhl", "stkaiti")

# 风格预设：柔和外扩辉光 + 可选细描边（贴近抖音短剧/漫剧标题）
class _EffectStyle(TypedDict):
    label: str
    default_glow: str
    radii: tuple[float, ...]
    opacities: tuple[float, ...]
    steps: int
    outline_ratio: float
    outline_color: str
    prefer_fonts: tuple[str, ...]
    suggest_fill: str
    core_shadow: bool


def _style(
    label: str,
    glow: str,
    *,
    radii: tuple[float, ...] = (0.14, 0.28, 0.46, 0.68),
    opacities: tuple[float, ...] = (0.45, 0.26, 0.13, 0.05),
    steps: int = 8,
    outline_ratio: float = 0.06,
    outline_color: str = "#000000",
    prefer_fonts: tuple[str, ...] = _BRUSH_FONTS,
    suggest_fill: str = "#FFFFFF",
    core_shadow: bool = False,
) -> _EffectStyle:
    return {
        "label": label,
        "default_glow": glow,
        "radii": radii,
        "opacities": opacities,
        "steps": steps,
        "outline_ratio": outline_ratio,
        "outline_color": outline_color,
        "prefer_fonts": prefer_fonts,
        "suggest_fill": suggest_fill,
        "core_shadow": core_shadow,
    }


_EFFECT_STYLES: dict[str, _EffectStyle] = {
    "none": _style("无特效", "#FFFFFF", radii=(), opacities=(), steps=0, outline_ratio=0.0, prefer_fonts=(), suggest_fill=""),
    # —— 参考图同类 ——
    "glow": _style(
        "白字辉光",
        "#FFFFFF",
        radii=(0.16, 0.30, 0.48, 0.70),
        opacities=(0.45, 0.26, 0.13, 0.05),
        outline_ratio=0.07,
    ),
    "pink_mood": _style(
        "粉雾氛围",
        "#FF4FA3",
        radii=(0.14, 0.28, 0.46, 0.68),
        opacities=(0.48, 0.28, 0.14, 0.06),
        outline_ratio=0.05,
    ),
    "ice_white": _style(
        "冰白强辉",
        "#F5FBFF",
        radii=(0.18, 0.34, 0.54, 0.78),
        opacities=(0.55, 0.32, 0.16, 0.06),
        outline_ratio=0.08,
    ),
    "poster_white": _style(
        "海报大字",
        "#FFFFFF",
        radii=(0.12, 0.24, 0.40, 0.58),
        opacities=(0.40, 0.22, 0.10, 0.04),
        outline_ratio=0.11,
        prefer_fonts=_BOLD_FONTS,
    ),
    # —— 彩色氛围 ——
    "guochao": _style(
        "国潮痛字",
        "#FF2D6A",
        radii=(0.15, 0.30, 0.50, 0.72),
        opacities=(0.50, 0.30, 0.15, 0.06),
        outline_ratio=0.08,
        prefer_fonts=("stxingka", "stxinwei", "sthupo", "simkai"),
        core_shadow=True,
    ),
    "red_impact": _style(
        "血红冲击",
        "#FF1E3C",
        radii=(0.15, 0.30, 0.50, 0.72),
        opacities=(0.52, 0.30, 0.14, 0.05),
        outline_ratio=0.08,
        prefer_fonts=("sthupo", "stxingka", "stxinwei"),
        core_shadow=True,
    ),
    "sunset": _style(
        "日落粉橙",
        "#FF6B9D",
        radii=(0.14, 0.28, 0.48, 0.70),
        opacities=(0.46, 0.26, 0.12, 0.05),
        prefer_fonts=_SOFT_FONTS + _BRUSH_FONTS[:2],
    ),
    "rose_gold": _style(
        "玫瑰金",
        "#FF8FAB",
        radii=(0.14, 0.28, 0.46, 0.66),
        opacities=(0.44, 0.26, 0.12, 0.05),
        suggest_fill="#FFF0F5",
        prefer_fonts=("stcaiyun", "simyou", "stxingka"),
    ),
    "warm_gold": _style(
        "暖金爆款",
        "#FFB020",
        radii=(0.14, 0.28, 0.46, 0.66),
        opacities=(0.44, 0.26, 0.12, 0.05),
        outline_ratio=0.07,
        outline_color="#2A1600",
        prefer_fonts=("stxinwei", "sthupo", "stxingka"),
        suggest_fill="#FFF6D8",
    ),
    "soft_yellow": _style(
        "柔黄标题",
        "#FFE566",
        radii=(0.14, 0.28, 0.46, 0.66),
        opacities=(0.42, 0.24, 0.12, 0.05),
        outline_color="#3A2A00",
        prefer_fonts=("simyou", "stcaiyun", "fzstk"),
        suggest_fill="#FFFCE8",
    ),
    "manga_yellow": _style(
        "漫剧黄字",
        "#FFD400",
        radii=(0.10, 0.22, 0.38, 0.56),
        opacities=(0.38, 0.22, 0.10, 0.04),
        outline_ratio=0.12,
        prefer_fonts=_BOLD_FONTS,
        suggest_fill="#FFE566",
    ),
    "orange_fire": _style(
        "橙火爆款",
        "#FF6A00",
        radii=(0.15, 0.30, 0.50, 0.72),
        opacities=(0.48, 0.28, 0.14, 0.05),
        outline_color="#2A1000",
        prefer_fonts=("sthupo", "stxinwei", "msyhbd"),
        core_shadow=True,
    ),
    # —— 冷色 / 霓虹 ——
    "neon": _style(
        "青霓虹",
        "#00E5FF",
        radii=(0.12, 0.24, 0.40, 0.60),
        opacities=(0.42, 0.24, 0.12, 0.05),
        outline_ratio=0.05,
        outline_color="#001820",
        prefer_fonts=_BOLD_FONTS,
    ),
    "cold_blue": _style(
        "冷蓝情绪",
        "#5B8CFF",
        radii=(0.14, 0.28, 0.46, 0.66),
        opacities=(0.42, 0.24, 0.12, 0.05),
        prefer_fonts=("stxingka", "stxihei", "msyhbd"),
    ),
    "cyan_mint": _style(
        "薄荷绿",
        "#3DFFC8",
        radii=(0.14, 0.28, 0.46, 0.66),
        opacities=(0.42, 0.24, 0.12, 0.05),
        outline_color="#003528",
        prefer_fonts=("simyou", "msyhbd", "stxihei"),
    ),
    "purple_dream": _style(
        "紫幻柔光",
        "#B44DFF",
        radii=(0.14, 0.28, 0.48, 0.70),
        opacities=(0.46, 0.26, 0.13, 0.05),
        prefer_fonts=("stxingka", "stcaiyun", "fzstk"),
    ),
    "violet_neon": _style(
        "紫霓虹",
        "#C77DFF",
        radii=(0.12, 0.24, 0.42, 0.62),
        opacities=(0.44, 0.26, 0.12, 0.05),
        outline_color="#1A0030",
        prefer_fonts=_BOLD_FONTS,
    ),
    "deep_purple": _style(
        "深紫悬疑",
        "#7B2FFF",
        radii=(0.15, 0.30, 0.50, 0.72),
        opacities=(0.48, 0.28, 0.14, 0.05),
        prefer_fonts=("stzhongs", "msyhbd", "stxingka"),
        core_shadow=True,
    ),
    "cyber_lime": _style(
        "赛博黄绿",
        "#B8FF00",
        radii=(0.12, 0.24, 0.40, 0.60),
        opacities=(0.44, 0.26, 0.12, 0.05),
        outline_color="#1A2200",
        prefer_fonts=_BOLD_FONTS,
        suggest_fill="#F5FFE8",
    ),
    "ink_red": _style(
        "朱红国风",
        "#E6392B",
        radii=(0.14, 0.28, 0.46, 0.66),
        opacities=(0.44, 0.26, 0.12, 0.05),
        outline_ratio=0.07,
        prefer_fonts=("stliti", "simli", "stxingka", "fzstk"),
        suggest_fill="#FFF5F2",
        core_shadow=True,
    ),
    # —— 纯描边可读 ——
    "outline": _style(
        "黑描边白字",
        "#FFFFFF",
        radii=(),
        opacities=(),
        steps=0,
        outline_ratio=0.10,
        prefer_fonts=_BOLD_FONTS,
    ),
    "heavy_outline": _style(
        "粗黑描边",
        "#FFFFFF",
        radii=(),
        opacities=(),
        steps=0,
        outline_ratio=0.16,
        prefer_fonts=_BOLD_FONTS,
    ),
}

EFFECT_CHOICES: tuple[tuple[str, str], ...] = tuple(
    (eid, style["label"]) for eid, style in _EFFECT_STYLES.items()
)
_EFFECT_DEFAULT_GLOW: dict[str, str] = {
    eid: style["default_glow"] for eid, style in _EFFECT_STYLES.items()
}

DEFAULT_TITLE_PORTRAIT = {
    "x_pct": 4.0,
    "y_pct": 94.5,
    "font": DEFAULT_FONT,
    "fontsize": 22,
    "color": "#FFFFFF",
    "opacity": 0.8,
    "layout": "horizontal",
    "effect": "none",
    "glow_color": "#FFFFFF",
}
DEFAULT_TITLE_LANDSCAPE = {
    "x_pct": 2.5,
    "y_pct": 90.0,
    "font": DEFAULT_FONT,
    "fontsize": 22,
    "color": "#FFFFFF",
    "opacity": 0.8,
    "layout": "horizontal",
    "effect": "none",
    "glow_color": "#FFFFFF",
}
DEFAULT_DISCLAIMER_PORTRAIT = {
    "x_pct": 4.0,
    "y_pct": 96.9,
    "font": DEFAULT_FONT,
    "fontsize": 14,
    "color": "#FFFFFF",
    "opacity": 0.6,
    "layout": "horizontal",
    "effect": "none",
    "glow_color": "#FFFFFF",
}
DEFAULT_DISCLAIMER_LANDSCAPE = {
    "x_pct": 2.5,
    "y_pct": 94.0,
    "font": DEFAULT_FONT,
    "fontsize": 14,
    "color": "#FFFFFF",
    "opacity": 0.6,
    "layout": "horizontal",
    "effect": "none",
    "glow_color": "#FFFFFF",
}

DEFAULT_TITLE: dict[str, Any] = {
    "text": "《{name}》",
    "font": DEFAULT_FONT,
    "fontsize": 22,
    "color": "#FFFFFF",
    "opacity": 0.8,
    "layout": "horizontal",
    "effect": "none",
    "glow_color": "#FFFFFF",
    "portrait": dict(DEFAULT_TITLE_PORTRAIT),
    "landscape": dict(DEFAULT_TITLE_LANDSCAPE),
}

DEFAULT_DISCLAIMER: dict[str, Any] = {
    "text": "内容纯属虚构 请勿带入现实",
    "font": DEFAULT_FONT,
    "fontsize": 14,
    "color": "#FFFFFF",
    "opacity": 0.6,
    "layout": "horizontal",
    "effect": "none",
    "glow_color": "#FFFFFF",
    "portrait": dict(DEFAULT_DISCLAIMER_PORTRAIT),
    "landscape": dict(DEFAULT_DISCLAIMER_LANDSCAPE),
}


class OverlayOrientStyle(TypedDict):
    """横或竖某一向的样式（含位置与字体参数）。"""

    x_pct: float
    y_pct: float
    font: str
    fontsize: int
    color: str
    opacity: float
    layout: TextLayout
    effect: TextEffect
    glow_color: str


# 兼容旧名
OverlayPos = OverlayOrientStyle


class OverlayTextStyle(TypedDict):
    text: str
    # 顶层字段为兼容旧配置 / 镜像当前竖屏；真源在 portrait/landscape
    font: str
    fontsize: int
    color: str
    opacity: float
    layout: TextLayout
    effect: TextEffect
    glow_color: str
    portrait: OverlayOrientStyle
    landscape: OverlayOrientStyle


def _clamp_float(value: Any, lo: float, hi: float, default: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


# 叠字字号范围（预览滚轮 / SpinBox / clamp 共用）
OVERLAY_FONTSIZE_MIN = 8
OVERLAY_FONTSIZE_MAX = 90


def clamp_overlay_fontsize(value: Any, default: int = 16) -> int:
    return _clamp_int(
        value, OVERLAY_FONTSIZE_MIN, OVERLAY_FONTSIZE_MAX, default
    )


def _normalize_color(value: Any, default: str = "#FFFFFF") -> str:
    raw = str(value or "").strip()
    if not raw:
        return default
    if raw.startswith("#"):
        raw = raw[1:]
    if len(raw) == 3 and all(c in "0123456789abcdefABCDEF" for c in raw):
        raw = "".join(c * 2 for c in raw)
    if len(raw) == 6 and all(c in "0123456789abcdefABCDEF" for c in raw):
        return f"#{raw.upper()}"
    return default


def clamp_font_key(value: Any) -> str:
    key = str(value or "").strip().lower()
    if key in _FONT_BY_KEY:
        return key
    for k, (_label, filename) in _FONT_BY_KEY.items():
        stem = filename.lower().rsplit(".", 1)[0]
        if key == filename.lower() or key == stem:
            return k
    return DEFAULT_FONT


def font_filename(font_key: str) -> str:
    return _FONT_BY_KEY[clamp_font_key(font_key)][1]


def font_label(font_key: str) -> str:
    return _FONT_BY_KEY[clamp_font_key(font_key)][0]


def available_font_choices() -> list[tuple[str, str, str]]:
    """本机 Fonts 目录中实际存在的字体（核心字体始终保留）。"""
    windir = os.environ.get("WINDIR", "C:/Windows")
    fonts_dir = os.path.join(windir, "Fonts")
    out: list[tuple[str, str, str]] = []
    for key, label, filename in FONT_CHOICES:
        path = os.path.join(fonts_dir, filename)
        if key in _CORE_FONTS or os.path.isfile(path):
            out.append((key, label, filename))
    return out


def known_font_keys() -> set[str]:
    return set(_FONT_BY_KEY)


def known_effect_ids() -> set[str]:
    return set(_EFFECT_STYLES)

def clamp_text_effect(value: Any) -> TextEffect:
    key = str(value or "").strip().lower()
    if key in _EFFECT_STYLES:
        return key  # type: ignore[return-value]
    return "none"


def effect_style(effect: TextEffect | str) -> _EffectStyle:
    return _EFFECT_STYLES[clamp_text_effect(effect)]


def _soft_glow_offsets(
    effect: TextEffect, fontsize: int
) -> list[tuple[float, float, float]]:
    """柔和辉光副本：(dx, dy, 相对透明度)。沿字形四周外扩成雾状光晕。"""
    style = effect_style(effect)
    radii, opacities, steps = style["radii"], style["opacities"], style["steps"]
    if not radii or steps <= 0:
        return []
    out: list[tuple[float, float, float]] = []
    # 中心薄雾 + 近缘加厚，贴近短剧「外发光」观感
    out.append((0.0, 0.0, opacities[0] * 0.65))
    for r_mul, op in zip(radii, opacities):
        radius = max(1.0, float(fontsize) * float(r_mul))
        for i in range(steps):
            ang = (2.0 * math.pi * i) / steps
            out.append((radius * math.cos(ang), radius * math.sin(ang), op))
    return out


def _outline_borderw(effect: TextEffect, fontsize: int) -> int:
    ratio = float(effect_style(effect)["outline_ratio"] or 0.0)
    if ratio <= 0:
        return 0
    return max(1, int(round(fontsize * ratio)))


def effect_label(effect: TextEffect | str) -> str:
    return effect_style(effect)["label"]


def resolve_glow_color(style: OverlayTextStyle | dict) -> str:
    """发光色：显式配置优先，否则按特效默认。"""
    effect = clamp_text_effect(style.get("effect"))
    raw = str(style.get("glow_color") or "").strip()
    if raw:
        return _normalize_color(raw, _EFFECT_DEFAULT_GLOW[effect])
    if effect in {"glow", "ice_white", "poster_white", "outline", "heavy_outline"}:
        return _normalize_color(style.get("color"), "#FFFFFF")
    return _EFFECT_DEFAULT_GLOW[effect]


def _clamp_orient_style(
    data: Any,
    defaults_orient: dict[str, Any],
    top_fallback: dict[str, Any],
) -> OverlayOrientStyle:
    """钳制某一向样式；缺字体等字段时从顶层旧字段迁移。"""
    src = data if isinstance(data, dict) else {}

    def _has(key: str) -> bool:
        return key in src and src.get(key) is not None and str(src.get(key)).strip() != ""

    def _pick(key: str, default: Any) -> Any:
        if _has(key):
            return src.get(key)
        if key in top_fallback and top_fallback.get(key) is not None:
            return top_fallback.get(key)
        return defaults_orient.get(key, default)

    effect = clamp_text_effect(_pick("effect", defaults_orient.get("effect", "none")))
    raw_glow = src.get("glow_color") if _has("glow_color") else top_fallback.get("glow_color")
    if raw_glow is None or not str(raw_glow).strip():
        glow_color = _EFFECT_DEFAULT_GLOW[effect]
        if effect == "none":
            glow_color = _normalize_color(
                defaults_orient.get("glow_color"), glow_color
            )
    else:
        glow_color = _normalize_color(raw_glow, _EFFECT_DEFAULT_GLOW[effect])

    return {
        "x_pct": _clamp_float(
            src.get("x_pct", defaults_orient.get("x_pct", 0.0)),
            0.0,
            100.0,
            float(defaults_orient.get("x_pct", 0.0)),
        ),
        "y_pct": _clamp_float(
            src.get("y_pct", defaults_orient.get("y_pct", 0.0)),
            0.0,
            100.0,
            float(defaults_orient.get("y_pct", 0.0)),
        ),
        "font": clamp_font_key(_pick("font", defaults_orient.get("font", DEFAULT_FONT))),
        "fontsize": clamp_overlay_fontsize(
            _pick("fontsize", defaults_orient.get("fontsize", 16)),
            int(defaults_orient.get("fontsize", 16)),
        ),
        "color": _normalize_color(
            _pick("color", defaults_orient.get("color", "#FFFFFF")),
            str(defaults_orient.get("color", "#FFFFFF")),
        ),
        "opacity": _clamp_float(
            _pick("opacity", defaults_orient.get("opacity", 1.0)),
            0.0,
            1.0,
            float(defaults_orient.get("opacity", 1.0)),
        ),
        "layout": clamp_text_layout(
            _pick("layout", defaults_orient.get("layout", "horizontal"))
        ),
        "effect": effect,
        "glow_color": glow_color,
    }


def clamp_text_layout(value: Any) -> TextLayout:
    if str(value or "").strip().lower() == "vertical":
        return "vertical"
    return "horizontal"


def clamp_overlay_style(
    data: dict | None, defaults: dict[str, Any]
) -> OverlayTextStyle:
    src = data if isinstance(data, dict) else {}
    text = src.get("text")
    if text is None:
        text = defaults["text"]
    else:
        text = str(text)

    def_portrait = defaults.get("portrait") or {
        "x_pct": float(defaults.get("x_pct", 0.0)),
        "y_pct": float(defaults.get("y_pct", 0.0)),
        "font": defaults.get("font", DEFAULT_FONT),
        "fontsize": defaults.get("fontsize", 16),
        "color": defaults.get("color", "#FFFFFF"),
        "opacity": defaults.get("opacity", 1.0),
        "layout": defaults.get("layout", "horizontal"),
        "effect": defaults.get("effect", "none"),
        "glow_color": defaults.get("glow_color", "#FFFFFF"),
    }
    def_landscape = defaults.get("landscape") or dict(def_portrait)

    # 顶层旧字段：迁移进尚未带字体参数的横/竖桶
    top_fallback = {
        "font": src.get("font", defaults.get("font")),
        "fontsize": src.get("fontsize", defaults.get("fontsize")),
        "color": src.get("color", defaults.get("color")),
        "opacity": src.get("opacity", defaults.get("opacity")),
        "layout": src.get("layout", defaults.get("layout")),
        "effect": src.get("effect", defaults.get("effect")),
        "glow_color": src.get("glow_color", defaults.get("glow_color")),
    }

    if isinstance(src.get("portrait"), dict):
        portrait_src = src["portrait"]
    elif "x_pct" in src or "y_pct" in src:
        portrait_src = {"x_pct": src.get("x_pct"), "y_pct": src.get("y_pct")}
    else:
        portrait_src = None

    if isinstance(src.get("landscape"), dict):
        landscape_src = src["landscape"]
    else:
        landscape_src = None

    portrait = _clamp_orient_style(portrait_src, def_portrait, top_fallback)
    landscape = _clamp_orient_style(landscape_src, def_landscape, top_fallback)

    # 顶层镜像竖屏，兼容只读顶层字段的旧逻辑
    return {
        "text": text,
        "font": portrait["font"],
        "fontsize": portrait["fontsize"],
        "color": portrait["color"],
        "opacity": portrait["opacity"],
        "layout": portrait["layout"],
        "effect": portrait["effect"],
        "glow_color": portrait["glow_color"],
        "portrait": portrait,
        "landscape": landscape,
    }


def position_for_orientation(
    style: OverlayTextStyle | dict, orientation: Orientation
) -> OverlayOrientStyle:
    key: Orientation = "landscape" if orientation == "landscape" else "portrait"
    pos = style.get(key) if isinstance(style, dict) else None
    if isinstance(pos, dict) and "x_pct" in pos and "y_pct" in pos:
        # 可能仍是旧仅坐标桶；用 clamp 补齐
        top = {
            "font": style.get("font"),
            "fontsize": style.get("fontsize"),
            "color": style.get("color"),
            "opacity": style.get("opacity"),
            "layout": style.get("layout"),
            "effect": style.get("effect"),
            "glow_color": style.get("glow_color"),
        }
        return _clamp_orient_style(pos, pos, top)
    return _clamp_orient_style(
        {"x_pct": style.get("x_pct"), "y_pct": style.get("y_pct")},
        {"x_pct": 0.0, "y_pct": 0.0},
        {
            "font": style.get("font"),
            "fontsize": style.get("fontsize"),
            "color": style.get("color"),
            "opacity": style.get("opacity"),
            "layout": style.get("layout"),
            "effect": style.get("effect"),
            "glow_color": style.get("glow_color"),
        },
    )


def style_for_orientation(
    style: OverlayTextStyle | dict,
    orientation: Orientation,
    *,
    defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """合并文案 + 当前方向样式，供预览/表单/渲染使用。"""
    base = defaults or DEFAULT_TITLE
    s = clamp_overlay_style(dict(style) if isinstance(style, dict) else None, base)
    orient = position_for_orientation(s, orientation)
    return {
        "text": s["text"],
        "font": orient["font"],
        "fontsize": orient["fontsize"],
        "color": orient["color"],
        "opacity": orient["opacity"],
        "layout": orient["layout"],
        "effect": orient["effect"],
        "glow_color": orient["glow_color"],
        "x_pct": orient["x_pct"],
        "y_pct": orient["y_pct"],
        "portrait": s["portrait"],
        "landscape": s["landscape"],
    }


def update_orient_style(
    style: dict,
    orientation: Orientation,
    fields: dict[str, Any],
    *,
    defaults: dict[str, Any] | None = None,
) -> OverlayTextStyle:
    """写入某一向的样式字段（字体/字号/特效/坐标等），不影响另一向。"""
    key: Orientation = "landscape" if orientation == "landscape" else "portrait"
    out = dict(style)
    cur = dict(out.get(key) if isinstance(out.get(key), dict) else {})
    cur.update(fields)
    out[key] = cur
    # 顶层镜像当前编辑方向，便于旧字段读取
    for k in (
        "font",
        "fontsize",
        "color",
        "opacity",
        "layout",
        "effect",
        "glow_color",
    ):
        if k in fields:
            out[k] = fields[k]
    return clamp_overlay_style(out, defaults or DEFAULT_TITLE)


def set_position_for_orientation(
    style: dict,
    orientation: Orientation,
    x_pct: float,
    y_pct: float,
) -> dict:
    key: Orientation = "landscape" if orientation == "landscape" else "portrait"
    out = dict(style)
    cur = dict(out.get(key) if isinstance(out.get(key), dict) else {})
    cur["x_pct"] = _clamp_float(x_pct, 0.0, 100.0, 0.0)
    cur["y_pct"] = _clamp_float(y_pct, 0.0, 100.0, 0.0)
    out[key] = cur
    return out


def default_overlay_title() -> OverlayTextStyle:
    return clamp_overlay_style(None, DEFAULT_TITLE)


def default_overlay_disclaimer() -> OverlayTextStyle:
    return clamp_overlay_style(None, DEFAULT_DISCLAIMER)


def _parse_json_cfg(raw: Any) -> dict | None:
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


# ---- 文字组库 ----

DEFAULT_OVERLAY_GROUP_ID = "default"
DEFAULT_OVERLAY_GROUP_NAME = "默认"


class OverlayTextGroup(TypedDict):
    id: str
    name: str
    title: OverlayTextStyle
    disclaimer: OverlayTextStyle


class OverlayTextLibrary(TypedDict):
    selected_id: str
    groups: list[OverlayTextGroup]


def _new_group_id() -> str:
    return uuid.uuid4().hex


def _clamp_group(raw: Any) -> OverlayTextGroup | None:
    if not isinstance(raw, dict):
        return None
    gid = str(raw.get("id") or "").strip() or _new_group_id()
    name = str(raw.get("name") or "").strip() or DEFAULT_OVERLAY_GROUP_NAME
    title = clamp_overlay_style(
        raw.get("title") if isinstance(raw.get("title"), dict) else None,
        DEFAULT_TITLE,
    )
    disc = clamp_overlay_style(
        raw.get("disclaimer") if isinstance(raw.get("disclaimer"), dict) else None,
        DEFAULT_DISCLAIMER,
    )
    return {"id": gid, "name": name[:64], "title": title, "disclaimer": disc}


def make_overlay_group(
    *,
    name: str,
    title: dict | OverlayTextStyle | None = None,
    disclaimer: dict | OverlayTextStyle | None = None,
    group_id: str | None = None,
) -> OverlayTextGroup:
    return {
        "id": (group_id or _new_group_id()).strip() or _new_group_id(),
        "name": (str(name).strip() or DEFAULT_OVERLAY_GROUP_NAME)[:64],
        "title": clamp_overlay_style(
            dict(title) if isinstance(title, dict) else None, DEFAULT_TITLE
        ),
        "disclaimer": clamp_overlay_style(
            dict(disclaimer) if isinstance(disclaimer, dict) else None,
            DEFAULT_DISCLAIMER,
        ),
    }


def ensure_default_overlay_group(lib: OverlayTextLibrary) -> OverlayTextLibrary:
    """保证存在 id=default 的「默认」组。"""
    groups = list(lib.get("groups") or [])
    found = next((g for g in groups if g["id"] == DEFAULT_OVERLAY_GROUP_ID), None)
    if found is None:
        groups.insert(
            0,
            make_overlay_group(
                name=DEFAULT_OVERLAY_GROUP_NAME,
                group_id=DEFAULT_OVERLAY_GROUP_ID,
            ),
        )
    else:
        # 保持默认组 id 稳定；名称允许用户改，空则还原
        if not str(found.get("name") or "").strip():
            found["name"] = DEFAULT_OVERLAY_GROUP_NAME
    selected = str(lib.get("selected_id") or "").strip()
    return {"selected_id": selected, "groups": groups}


def clamp_overlay_library(data: Any) -> OverlayTextLibrary:
    src = data if isinstance(data, dict) else {}
    groups: list[OverlayTextGroup] = []
    seen: set[str] = set()
    raw_groups = src.get("groups")
    if isinstance(raw_groups, list):
        for item in raw_groups:
            g = _clamp_group(item)
            if g is None or g["id"] in seen:
                continue
            seen.add(g["id"])
            groups.append(g)
    lib: OverlayTextLibrary = {
        "selected_id": str(src.get("selected_id") or "").strip(),
        "groups": groups,
    }
    return ensure_default_overlay_group(lib)


def _legacy_title_disclaimer() -> tuple[OverlayTextStyle, OverlayTextStyle]:
    from app.common.config import cfg

    title = clamp_overlay_style(
        _parse_json_cfg(cfg.overlay_title_json.value), DEFAULT_TITLE
    )
    disc = clamp_overlay_style(
        _parse_json_cfg(cfg.overlay_disclaimer_json.value), DEFAULT_DISCLAIMER
    )
    return title, disc


def _migrate_library_from_legacy() -> OverlayTextLibrary:
    title, disc = _legacy_title_disclaimer()
    return ensure_default_overlay_group(
        {
            "selected_id": DEFAULT_OVERLAY_GROUP_ID,
            "groups": [
                make_overlay_group(
                    name=DEFAULT_OVERLAY_GROUP_NAME,
                    title=title,
                    disclaimer=disc,
                    group_id=DEFAULT_OVERLAY_GROUP_ID,
                )
            ],
        }
    )


def load_overlay_library_from_cfg() -> OverlayTextLibrary:
    """读取文字组库；空库时从旧单套字段迁移并落盘。"""
    from qfluentwidgets import qconfig

    from app.common.config import cfg

    raw = _parse_json_cfg(cfg.overlay_text_library_json.value)
    if raw is None or not isinstance(raw.get("groups"), list) or not raw.get("groups"):
        lib = _migrate_library_from_legacy()
        qconfig.set(
            cfg.overlay_text_library_json, json.dumps(lib, ensure_ascii=False)
        )
        # 同步旧键，便于兼容读
        qconfig.set(
            cfg.overlay_title_json, json.dumps(lib["groups"][0]["title"], ensure_ascii=False)
        )
        qconfig.set(
            cfg.overlay_disclaimer_json,
            json.dumps(lib["groups"][0]["disclaimer"], ensure_ascii=False),
        )
        return lib
    return clamp_overlay_library(raw)


def save_overlay_library_to_cfg(lib: OverlayTextLibrary) -> OverlayTextLibrary:
    from qfluentwidgets import qconfig

    from app.common.config import cfg

    clamped = clamp_overlay_library(lib)
    qconfig.set(
        cfg.overlay_text_library_json, json.dumps(clamped, ensure_ascii=False)
    )
    # 兼容：把当前启用（或默认）组写回旧双字段
    active = resolve_active_overlay_group(clamped)
    qconfig.set(
        cfg.overlay_title_json, json.dumps(active["title"], ensure_ascii=False)
    )
    qconfig.set(
        cfg.overlay_disclaimer_json,
        json.dumps(active["disclaimer"], ensure_ascii=False),
    )
    return clamped


def list_overlay_groups() -> list[OverlayTextGroup]:
    return list(load_overlay_library_from_cfg()["groups"])


def find_overlay_group(
    lib: OverlayTextLibrary, group_id: str
) -> OverlayTextGroup | None:
    gid = str(group_id or "").strip()
    if not gid:
        return None
    for g in lib["groups"]:
        if g["id"] == gid:
            return g
    return None


def find_default_overlay_group(lib: OverlayTextLibrary) -> OverlayTextGroup:
    for g in lib["groups"]:
        if g["id"] == DEFAULT_OVERLAY_GROUP_ID:
            return g
    # ensure 之后不应走到这里；兜底再建
    return make_overlay_group(
        name=DEFAULT_OVERLAY_GROUP_NAME, group_id=DEFAULT_OVERLAY_GROUP_ID
    )


def resolve_active_overlay_group(
    lib: OverlayTextLibrary | None = None,
) -> OverlayTextGroup:
    """勾选组；无效或未勾选则回退默认组。"""
    data = lib if lib is not None else load_overlay_library_from_cfg()
    selected = find_overlay_group(data, data.get("selected_id", ""))
    if selected is not None:
        return selected
    return find_default_overlay_group(data)


def get_selected_overlay_group() -> OverlayTextGroup:
    return resolve_active_overlay_group()


def set_selected_overlay_id(group_id: str | None) -> OverlayTextLibrary:
    lib = load_overlay_library_from_cfg()
    gid = str(group_id or "").strip()
    if gid and find_overlay_group(lib, gid) is None:
        gid = ""
    lib["selected_id"] = gid
    return save_overlay_library_to_cfg(lib)


def upsert_overlay_group(group: OverlayTextGroup | dict) -> OverlayTextLibrary:
    lib = load_overlay_library_from_cfg()
    g = _clamp_group(group)
    if g is None:
        return lib
    if g["id"] == DEFAULT_OVERLAY_GROUP_ID and not g["name"].strip():
        g["name"] = DEFAULT_OVERLAY_GROUP_NAME
    replaced = False
    new_groups: list[OverlayTextGroup] = []
    for existing in lib["groups"]:
        if existing["id"] == g["id"]:
            new_groups.append(g)
            replaced = True
        else:
            new_groups.append(existing)
    if not replaced:
        new_groups.append(g)
    lib["groups"] = new_groups
    return save_overlay_library_to_cfg(lib)


def delete_overlay_group(group_id: str) -> OverlayTextLibrary:
    lib = load_overlay_library_from_cfg()
    gid = str(group_id or "").strip()
    if not gid or gid == DEFAULT_OVERLAY_GROUP_ID:
        return lib
    lib["groups"] = [g for g in lib["groups"] if g["id"] != gid]
    if lib["selected_id"] == gid:
        lib["selected_id"] = ""
    return save_overlay_library_to_cfg(lib)


def load_overlay_title_from_cfg() -> OverlayTextStyle:
    return dict(resolve_active_overlay_group()["title"])  # type: ignore[return-value]


def load_overlay_disclaimer_from_cfg() -> OverlayTextStyle:
    return dict(resolve_active_overlay_group()["disclaimer"])  # type: ignore[return-value]


def save_overlay_styles_to_cfg(
    title: dict | OverlayTextStyle,
    disclaimer: dict | OverlayTextStyle,
) -> tuple[OverlayTextStyle, OverlayTextStyle]:
    """写回当前启用组（无启用则写默认组），并同步旧双字段。"""
    lib = load_overlay_library_from_cfg()
    active = resolve_active_overlay_group(lib)
    title_c = clamp_overlay_style(dict(title), DEFAULT_TITLE)
    disc_c = clamp_overlay_style(dict(disclaimer), DEFAULT_DISCLAIMER)
    active = {
        **active,
        "title": title_c,
        "disclaimer": disc_c,
    }
    upsert_overlay_group(active)
    return title_c, disc_c


def _style_equals_default(style: Any, defaults: dict[str, Any]) -> bool:
    return clamp_overlay_style(
        style if isinstance(style, dict) else None, defaults
    ) == clamp_overlay_style(None, defaults)


def _library_equals_default(lib: Any) -> bool:
    clamped = clamp_overlay_library(lib)
    if len(clamped["groups"]) != 1:
        return False
    g = clamped["groups"][0]
    if g["id"] != DEFAULT_OVERLAY_GROUP_ID:
        return False
    return _style_equals_default(g["title"], DEFAULT_TITLE) and _style_equals_default(
        g["disclaimer"], DEFAULT_DISCLAIMER
    )


def apply_overlay_from_clip_edit_dict(data: dict | None) -> None:
    """从服务端 clip_edit 命名空间写入本地 cfg（含 export_name_tag 与叠字库）。"""
    if not data:
        return
    from qfluentwidgets import qconfig

    from app.common.config import cfg

    local_lib_raw = str(cfg.overlay_text_library_json.value or "").strip()

    if data.get("overlay_text_library") is not None:
        incoming = clamp_overlay_library(data.get("overlay_text_library"))
        # 本地已有非默认库时，忽略服务端空默认库，避免登录覆盖
        if local_lib_raw and not _library_equals_default(_parse_json_cfg(local_lib_raw)):
            if _library_equals_default(incoming):
                pass
            else:
                save_overlay_library_to_cfg(incoming)
        else:
            save_overlay_library_to_cfg(incoming)
    elif not local_lib_raw:
        # 兼容旧双字段 → 迁入默认组（仅本地尚无 library）
        def _should_apply(incoming: Any, defaults: dict[str, Any], local_raw: Any) -> bool:
            local = str(local_raw or "").strip()
            if not local:
                return True
            return not _style_equals_default(incoming, defaults)

        title = None
        disc = None
        if data.get("overlay_title") is not None and _should_apply(
            data.get("overlay_title"), DEFAULT_TITLE, cfg.overlay_title_json.value
        ):
            title = clamp_overlay_style(data.get("overlay_title"), DEFAULT_TITLE)
        if data.get("overlay_disclaimer") is not None and _should_apply(
            data.get("overlay_disclaimer"),
            DEFAULT_DISCLAIMER,
            cfg.overlay_disclaimer_json.value,
        ):
            disc = clamp_overlay_style(
                data.get("overlay_disclaimer"), DEFAULT_DISCLAIMER
            )
        if title is not None or disc is not None:
            save_overlay_library_to_cfg(
                {
                    "selected_id": DEFAULT_OVERLAY_GROUP_ID,
                    "groups": [
                        make_overlay_group(
                            name=DEFAULT_OVERLAY_GROUP_NAME,
                            title=title or default_overlay_title(),
                            disclaimer=disc or default_overlay_disclaimer(),
                            group_id=DEFAULT_OVERLAY_GROUP_ID,
                        )
                    ],
                }
            )

    if "export_name_tag" in data:
        qconfig.set(
            cfg.clip_export_name_tag,
            str(data.get("export_name_tag") or "").strip()[:20],
        )


def clip_edit_settings_patch(
    *,
    export_name_tag: str | None = None,
    overlay_title: dict | None = None,
    overlay_disclaimer: dict | None = None,
    overlay_text_library: dict | None = None,
) -> dict:
    clip: dict[str, Any] = {}
    if export_name_tag is not None:
        clip["export_name_tag"] = str(export_name_tag).strip()[:20]
    if overlay_text_library is not None:
        lib = clamp_overlay_library(overlay_text_library)
        clip["overlay_text_library"] = lib
        active = resolve_active_overlay_group(lib)
        clip["overlay_title"] = active["title"]
        clip["overlay_disclaimer"] = active["disclaimer"]
    else:
        if overlay_title is not None:
            clip["overlay_title"] = clamp_overlay_style(overlay_title, DEFAULT_TITLE)
        if overlay_disclaimer is not None:
            clip["overlay_disclaimer"] = clamp_overlay_style(
                overlay_disclaimer, DEFAULT_DISCLAIMER
            )
    return {"clip_edit": clip}

def resolve_overlay_text(template: str, project_name: str) -> str:
    """把模板中的 {name} 替换为剧名；空模板表示不显示。"""
    if template is None:
        return ""
    text = str(template)
    if not text.strip():
        return ""
    return text.replace("{name}", project_name)


# 竖排时横式书名号 → 竖式书名号（Presentation Form）
_VERTICAL_BOOK_TITLE_MARKS = str.maketrans({"《": "︽", "》": "︾"})


def apply_text_layout(text: str, layout: TextLayout | str) -> str:
    """按排布方式格式化文案；竖排则逐字换行，并将《》换成︽︾。"""
    if not text:
        return ""
    if clamp_text_layout(layout) != "vertical":
        return text
    chars: list[str] = []
    for ch in text.translate(_VERTICAL_BOOK_TITLE_MARKS):
        if ch in "\r\n":
            continue
        if ch == " ":
            chars.append("　")
            continue
        chars.append(ch)
    return "\n".join(chars)


def escape_drawtext(text: str) -> str:
    """转义单行文案，供 drawtext 的 text='...' 使用（勿含换行）。

    注意：FFmpeg drawtext 的 text= 不会把 \\n 解释成换行，只会画出字母 n。
    竖排请用 build_drawtext_filters 拆成多条 drawtext。
    """
    out = text.replace("\r", "").replace("\n", "")
    out = out.replace("\\", "\\\\")
    out = out.replace("'", r"\'")
    out = out.replace(":", r"\:")
    out = out.replace("%", "%%")
    return out


def prepare_font_file(font_key: str, work_dir: str | None = None) -> str:
    """确保字体可用，返回供 drawtext fontfile= 使用的路径。"""
    filename = font_filename(font_key)
    windir = os.environ.get("WINDIR", "C:/Windows")
    system_font = os.path.join(windir, "Fonts", filename)
    dest_dir = work_dir or os.getcwd()
    dest = os.path.join(dest_dir, filename)
    if not os.path.exists(dest) and os.path.exists(system_font):
        try:
            shutil.copy(system_font, dest)
        except Exception:
            pass
    if os.path.exists(dest):
        cwd = os.getcwd()
        if os.path.abspath(dest_dir) == os.path.abspath(cwd):
            return filename
        return dest.replace("\\", "/")
    if os.path.exists(system_font):
        return system_font.replace("\\", "/")
    return filename


def build_drawtext_filters(
    style: OverlayTextStyle | dict,
    *,
    project_name: str,
    fontfile: str | None = None,
    orientation: Orientation = "portrait",
) -> list[str]:
    """生成 drawtext 列表。竖排拆多条；短剧风格=柔光晕 + 细描边正文。"""
    defaults = {
        "text": "",
        "font": DEFAULT_FONT,
        "fontsize": 16,
        "color": "#FFFFFF",
        "opacity": 1.0,
        "layout": "horizontal",
        "effect": "none",
        "glow_color": "#FFFFFF",
        "portrait": {"x_pct": 0.0, "y_pct": 0.0},
        "landscape": {"x_pct": 0.0, "y_pct": 0.0},
    }
    s = clamp_overlay_style(dict(style), defaults)
    rendered = resolve_overlay_text(s["text"], project_name)
    if not rendered.strip():
        return []
    orient = position_for_orientation(s, orientation)
    rendered = apply_text_layout(rendered, orient["layout"])
    font = fontfile or prepare_font_file(orient["font"])
    font_esc = font.replace("\\", "/").replace(":", r"\:")
    color_hex = orient["color"].lstrip("#")
    glow_hex = resolve_glow_color(orient).lstrip("#")
    opacity = orient["opacity"]
    fontsize = orient["fontsize"]
    effect = clamp_text_effect(orient["effect"])
    estyle = effect_style(effect)
    glow_offsets = _soft_glow_offsets(effect, fontsize)
    outline_w = _outline_borderw(effect, fontsize)
    outline_hex = str(estyle["outline_color"]).lstrip("#")
    x_expr = f"w*{orient['x_pct'] / 100.0:.6f}"
    y0 = f"h*{orient['y_pct'] / 100.0:.6f}"
    line_gap = max(0, int(round(fontsize * 0.12)))

    lines = rendered.split("\n")
    filters: list[str] = []
    for i, line in enumerate(lines):
        text_esc = escape_drawtext(line if line else " ")
        y_expr = y0 if i == 0 else f"{y0}+{i}*({fontsize}+{line_gap})"
        # 1) 柔和外扩光晕（偏移叠字，不是彩色硬描边）
        for dx, dy, op_mul in glow_offsets:
            glow_op = max(0.02, min(1.0, opacity * op_mul))
            x_g = x_expr if abs(dx) < 1e-6 else f"{x_expr}+{dx:.2f}"
            y_g = y_expr if abs(dy) < 1e-6 else f"{y_expr}+{dy:.2f}"
            filters.append(
                f"drawtext=fontfile={font_esc}:text='{text_esc}':"
                f"x={x_g}:y={y_g}:fontsize={fontsize}:"
                f"fontcolor={glow_hex}@{glow_op:.3f}"
            )
        # 2) 正文：可选细黑描边（短剧标题常用，保证糊底可读）
        core = (
            f"drawtext=fontfile={font_esc}:text='{text_esc}':"
            f"x={x_expr}:y={y_expr}:fontsize={fontsize}:"
            f"fontcolor={color_hex}@{opacity}"
        )
        if outline_w > 0:
            core += f":borderw={outline_w}:bordercolor={outline_hex}@0.92"
        if estyle["core_shadow"]:
            core += ":shadowx=2:shadowy=2:shadowcolor=black@0.45"
        filters.append(core)
    return filters


def build_drawtext_filter(
    style: OverlayTextStyle | dict,
    *,
    project_name: str,
    fontfile: str | None = None,
    orientation: Orientation = "portrait",
) -> str | None:
    """生成 drawtext；多行时用逗号拼成一条 filter 链片段。空文案返回 None。"""
    parts = build_drawtext_filters(
        style,
        project_name=project_name,
        fontfile=fontfile,
        orientation=orientation,
    )
    if not parts:
        return None
    return ",".join(parts)


def build_overlay_drawtext_filters(
    project_name: str, *, horizontal: bool = False
) -> list[str]:
    """按当前 cfg 生成剧名+提示的 drawtext 列表（空文案跳过）。"""
    orientation: Orientation = "landscape" if horizontal else "portrait"
    title = load_overlay_title_from_cfg()
    disc = load_overlay_disclaimer_from_cfg()
    fonts_needed: set[str] = set()
    for style in (title, disc):
        if not resolve_overlay_text(style["text"], project_name).strip():
            continue
        fonts_needed.add(position_for_orientation(style, orientation)["font"])
    fontfiles = {k: prepare_font_file(k) for k in fonts_needed}

    filters: list[str] = []
    filters.extend(
        build_drawtext_filters(
            title,
            project_name=project_name,
            fontfile=fontfiles.get(
                position_for_orientation(title, orientation)["font"]
            ),
            orientation=orientation,
        )
    )
    filters.extend(
        build_drawtext_filters(
            disc,
            project_name=project_name,
            fontfile=fontfiles.get(
                position_for_orientation(disc, orientation)["font"]
            ),
            orientation=orientation,
        )
    )
    return filters
