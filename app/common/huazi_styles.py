"""综艺花字样式定义（多层描边/渐变/阴影，供 Pillow 预渲）。"""

from __future__ import annotations

from typing import Literal, TypedDict

LayerKind = Literal["shadow", "glow", "stroke", "fill", "fill_gradient"]


class HuaziLayer(TypedDict, total=False):
    kind: LayerKind
    # 单色（shadow/glow/stroke/fill）
    color: str
    # 渐变（fill_gradient）：上→下
    colors: tuple[str, str]
    # 相对字号的比例
    width: float  # stroke 宽度
    dx: float
    dy: float
    blur: float
    opacity: float


class HuaziStyle(TypedDict):
    id: str
    label: str
    layers: tuple[HuaziLayer, ...]
    prefer_fonts: tuple[str, ...]
    # 预览卡片/默认正文色提示
    preview_color: str


_BOLD = ("msyhbd", "simhei", "sthupo", "stzhongs")
_BRUSH = ("stxingka", "stxinwei", "sthupo", "simkai")


def _L(**kwargs: object) -> HuaziLayer:
    return kwargs  # type: ignore[return-value]


# 自下而上绘制；效果接近剪映综艺贴纸/霓虹/立体字
HUAZI_STYLES: dict[str, HuaziStyle] = {
    "hz_sticker_pink": {
        "id": "hz_sticker_pink",
        "label": "粉描贴纸",
        "preview_color": "#FF5AA5",
        "prefer_fonts": _BOLD,
        "layers": (
            _L(kind="shadow", color="#000000", dx=0.12, dy=0.14, width=0.18, opacity=0.55),
            _L(kind="stroke", color="#FFFFFF", width=0.28),
            _L(kind="stroke", color="#FF4FA3", width=0.16),
            _L(kind="fill", color="#FFFFFF"),
        ),
    },
    "hz_sticker_orange": {
        "id": "hz_sticker_orange",
        "label": "橙描贴纸",
        "preview_color": "#FF7A1A",
        "prefer_fonts": _BOLD,
        "layers": (
            _L(kind="shadow", color="#000000", dx=0.12, dy=0.14, width=0.18, opacity=0.55),
            _L(kind="stroke", color="#FFFFFF", width=0.28),
            _L(kind="stroke", color="#FF6A00", width=0.16),
            _L(kind="fill", color="#FFF6E8"),
        ),
    },
    "hz_pop_yellow": {
        "id": "hz_pop_yellow",
        "label": "漫剧黄描",
        "preview_color": "#FFD400",
        "prefer_fonts": _BOLD,
        "layers": (
            _L(kind="shadow", color="#000000", dx=0.10, dy=0.12, width=0.14, opacity=0.65),
            _L(kind="stroke", color="#1A1A1A", width=0.22),
            _L(kind="fill", color="#FFE566"),
        ),
    },
    "hz_gold_3d": {
        "id": "hz_gold_3d",
        "label": "立体金边",
        "preview_color": "#FFC107",
        "prefer_fonts": _BOLD + _BRUSH[:1],
        "layers": (
            _L(kind="shadow", color="#4A2A00", dx=0.14, dy=0.16, width=0.12, opacity=0.85),
            _L(kind="shadow", color="#8B5A00", dx=0.07, dy=0.08, width=0.10, opacity=0.9),
            _L(kind="stroke", color="#FFF3C4", width=0.14),
            _L(kind="fill_gradient", colors=("#FFE082", "#FF8F00")),
        ),
    },
    "hz_neon_cyan": {
        "id": "hz_neon_cyan",
        "label": "青霓虹贴",
        "preview_color": "#00E5FF",
        "prefer_fonts": _BOLD,
        "layers": (
            _L(kind="glow", color="#00E5FF", blur=0.45, opacity=0.55),
            _L(kind="glow", color="#7AFFFF", blur=0.22, opacity=0.7),
            _L(kind="stroke", color="#003844", width=0.12),
            _L(kind="fill", color="#E8FFFF"),
        ),
    },
    "hz_violet_glow": {
        "id": "hz_violet_glow",
        "label": "紫霓虹贴",
        "preview_color": "#C77DFF",
        "prefer_fonts": _BOLD,
        "layers": (
            _L(kind="glow", color="#B44DFF", blur=0.48, opacity=0.55),
            _L(kind="glow", color="#E0B0FF", blur=0.22, opacity=0.65),
            _L(kind="stroke", color="#2A0044", width=0.12),
            _L(kind="fill", color="#F5E8FF"),
        ),
    },
    "hz_red_impact": {
        "id": "hz_red_impact",
        "label": "血红描边",
        "preview_color": "#FF1E3C",
        "prefer_fonts": _BRUSH,
        "layers": (
            _L(kind="shadow", color="#000000", dx=0.11, dy=0.13, width=0.16, opacity=0.7),
            _L(kind="stroke", color="#FFFFFF", width=0.24),
            _L(kind="stroke", color="#FF1E3C", width=0.12),
            _L(kind="fill", color="#FFFFFF"),
        ),
    },
    "hz_ice_blue": {
        "id": "hz_ice_blue",
        "label": "冰蓝渐变",
        "preview_color": "#5B8CFF",
        "prefer_fonts": _BOLD,
        "layers": (
            _L(kind="glow", color="#5B8CFF", blur=0.35, opacity=0.45),
            _L(kind="stroke", color="#FFFFFF", width=0.20),
            _L(kind="stroke", color="#3D6BFF", width=0.10),
            _L(kind="fill_gradient", colors=("#F0F7FF", "#4D8CFF")),
        ),
    },
    "hz_lime_pop": {
        "id": "hz_lime_pop",
        "label": "赛博黄绿",
        "preview_color": "#B8FF00",
        "prefer_fonts": _BOLD,
        "layers": (
            _L(kind="shadow", color="#1A2200", dx=0.10, dy=0.12, width=0.14, opacity=0.75),
            _L(kind="stroke", color="#1A2200", width=0.18),
            _L(kind="fill_gradient", colors=("#F5FFE8", "#B8FF00")),
        ),
    },
    "hz_white_black": {
        "id": "hz_white_black",
        "label": "黑白厚描",
        "preview_color": "#FFFFFF",
        "prefer_fonts": _BOLD,
        "layers": (
            _L(kind="shadow", color="#000000", dx=0.10, dy=0.12, width=0.10, opacity=0.5),
            _L(kind="stroke", color="#000000", width=0.26),
            _L(kind="fill", color="#FFFFFF"),
        ),
    },
    "hz_rose_soft": {
        "id": "hz_rose_soft",
        "label": "玫瑰柔光",
        "preview_color": "#FF8FAB",
        "prefer_fonts": ("stcaiyun", "simyou", "stxingka"),
        "layers": (
            _L(kind="glow", color="#FF8FAB", blur=0.40, opacity=0.50),
            _L(kind="stroke", color="#FFFFFF", width=0.18),
            _L(kind="stroke", color="#FF6B9D", width=0.08),
            _L(kind="fill_gradient", colors=("#FFFFFF", "#FFB7C5")),
        ),
    },
    "hz_ink_red": {
        "id": "hz_ink_red",
        "label": "朱红国风",
        "preview_color": "#E6392B",
        "prefer_fonts": ("stliti", "simli", "stxingka", "fzstk"),
        "layers": (
            _L(kind="shadow", color="#3A0000", dx=0.08, dy=0.10, width=0.10, opacity=0.55),
            _L(kind="stroke", color="#FFF5F2", width=0.16),
            _L(kind="stroke", color="#E6392B", width=0.08),
            _L(kind="fill", color="#FFF5F2"),
        ),
    },
}

HUAZI_STYLE_IDS: frozenset[str] = frozenset(HUAZI_STYLES.keys())


def is_huazi_effect(effect_id: str | None) -> bool:
    return str(effect_id or "").strip().lower() in HUAZI_STYLE_IDS


def get_huazi_style(effect_id: str) -> HuaziStyle | None:
    return HUAZI_STYLES.get(str(effect_id or "").strip().lower())
