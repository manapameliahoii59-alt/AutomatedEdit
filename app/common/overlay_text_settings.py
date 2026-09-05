"""渲染画面叠字（剧名 / 提示）设置：默认值、clamp、drawtext 生成、cfg 读写。"""

from __future__ import annotations

import builtins
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Literal, TypedDict

Orientation = Literal["portrait", "landscape"]
TextLayout = Literal["horizontal", "vertical"]
HAlign = Literal["l", "c", "r"]
VAlign = Literal["t", "c", "b"]
# 具体取值见 _EFFECT_STYLES；未知 id 会 clamp 为 none
TextEffect = str

# 字体 key -> (显示名, 主文件名)
# 解析顺序：tools/fonts → 工程根 → Windows Fonts → 用户 Fonts
# 仅实际找得到文件的会出现在下拉（核心字体始终保留）
FONT_CHOICES: tuple[tuple[str, str, str], ...] = (
    # 短剧/剪映常用标题字体（靠前；文件在 tools/fonts）
    ("qingkebenyue", "清刻本悦", "QingKeBenYue.ttf"),
    ("meihuakai", "梅花楷", "MeiHuaKai.ttf"),
    ("houxiandai", "后现代体", "HouXianDai.otf"),
    ("sourcehanserif", "思源中宋", "NotoSerifSC-Medium.otf"),
    ("ruoyan", "若烟体", "RuoYan.ttf"),
    ("tiantianquan", "甜甜圈", "TianTianQuan.ttf"),
    ("kuaile", "快乐体", "KuaiLeTi.ttf"),
    ("qingxue", "晴雪体", "QingXue.ttf"),
    ("menghuai", "梦槐体", "MengHuai.ttf"),
    ("msyh", "微软雅黑", "msyh.ttc"),
    ("msyhbd", "微软雅黑粗体", "msyhbd.ttc"),
    ("msyhl", "微软雅黑细体", "msyhl.ttc"),
    ("simhei", "黑体", "simhei.ttf"),
    ("simsun", "宋体", "simsun.ttc"),
    # 成片 drawtext 会回退到 simsun：simsunb.ttf 在 FFmpeg 下无汉字轮廓
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

# 同款字体的常见别名文件名（系统安装名 / 厂商原名）
_FONT_FILE_ALIASES: dict[str, tuple[str, ...]] = {
    "qingkebenyue": (
        "FZQingKeBenYueSongS.TTF",
        "FZQingKeBenYueSongJF.TTF",
        "方正清刻本悦宋简体.ttf",
    ),
    "meihuakai": ("Xique-MeihuaKai.ttf", "喜鹊梅花楷.ttf", "MeihuaKai.ttf"),
    "houxiandai": (
        "WenYue-HouXianDaiTi-W4-75-J.otf",
        "WenYue_HouXianDaiTi_J-W4_75.otf",
        "文悦后现代体.otf",
    ),
    "sourcehanserif": (
        "SourceHanSerifSC-Medium.otf",
        "NotoSerifCJKsc-Medium.otf",
        "NotoSerifSC-Medium.ttf",
    ),
    "ruoyan": ("RuoYanTi.ttf", "若烟体.ttf"),
    "tiantianquan": ("AaTianTianQuan.ttf", "甜甜圈.ttf", "Donut.ttf"),
    "kuaile": ("KuaiLeTi.ttf", "快乐体.ttf", "HappyFont.ttf"),
    "qingxue": ("QingXueTi.ttf", "晴雪体.ttf"),
    "menghuai": ("MengHuaiTi.ttf", "梦槐体.ttf"),
}

_FONT_BY_KEY = {k: (label, filename) for k, label, filename in FONT_CHOICES}
DEFAULT_FONT = "msyh"
_CORE_FONTS = {"msyh", "msyhbd", "simhei", "simsun", "simkai"}
_BRUSH_FONTS = ("stxingka", "fzstk", "fzytk", "stxinwei", "sthupo", "simkai")
_BOLD_FONTS = ("msyhbd", "simhei", "stzhongs", "sthupo")
_SOFT_FONTS = ("simyou", "stcaiyun", "msyhl", "stkaiti")

# 风格预设：柔和外扩辉光 + 可选细描边（贴近抖音/剪映标题花字）
# category: basic | hot | soft | neon | outline —— 供花字墙分组
class _EffectStyle(TypedDict):
    label: str
    category: str
    default_glow: str
    radii: tuple[float, ...]
    opacities: tuple[float, ...]
    steps: int
    outline_ratio: float
    outline_color: str
    prefer_fonts: tuple[str, ...]
    suggest_fill: str
    core_shadow: bool


# 默认：少圈、近缘、密采样 —— 避免旧版大半径稀疏叠字的重影感
_DEFAULT_RADII = (0.08, 0.16, 0.26)
_DEFAULT_OPACITIES = (0.30, 0.17, 0.08)
_DEFAULT_STEPS = 12


def _style(
    label: str,
    glow: str,
    *,
    category: str = "hot",
    radii: tuple[float, ...] = _DEFAULT_RADII,
    opacities: tuple[float, ...] = _DEFAULT_OPACITIES,
    steps: int = _DEFAULT_STEPS,
    outline_ratio: float = 0.06,
    outline_color: str = "#000000",
    prefer_fonts: tuple[str, ...] = _BRUSH_FONTS,
    suggest_fill: str = "#FFFFFF",
    core_shadow: bool = False,
) -> _EffectStyle:
    return {
        "label": label,
        "category": category,
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
    "none": _style(
        "无特效",
        "#FFFFFF",
        category="basic",
        radii=(),
        opacities=(),
        steps=0,
        outline_ratio=0.0,
        prefer_fonts=(),
        suggest_fill="",
    ),
    # —— 基础辉光 ——
    "glow": _style(
        "白字辉光",
        "#FFFFFF",
        category="basic",
        radii=(0.09, 0.17, 0.28),
        opacities=(0.32, 0.18, 0.08),
        outline_ratio=0.07,
    ),
    "ice_white": _style(
        "冰白强辉",
        "#F5FBFF",
        category="basic",
        radii=(0.10, 0.20, 0.32),
        opacities=(0.36, 0.20, 0.09),
        outline_ratio=0.08,
    ),
    "poster_white": _style(
        "海报大字",
        "#FFFFFF",
        category="basic",
        radii=(0.07, 0.14, 0.22),
        opacities=(0.28, 0.15, 0.07),
        outline_ratio=0.11,
        prefer_fonts=_BOLD_FONTS,
    ),
    # —— 热门花字 ——
    "pink_mood": _style(
        "粉雾氛围",
        "#FF4FA3",
        category="hot",
        radii=(0.08, 0.16, 0.26),
        opacities=(0.34, 0.18, 0.08),
        outline_ratio=0.05,
    ),
    "candy_pink": _style(
        "糖果粉",
        "#FF6EC7",
        category="hot",
        radii=(0.08, 0.16, 0.26),
        opacities=(0.32, 0.17, 0.08),
        prefer_fonts=_SOFT_FONTS + _BRUSH_FONTS[:2],
        suggest_fill="#FFF5FB",
    ),
    "guochao": _style(
        "国潮痛字",
        "#FF2D6A",
        category="hot",
        radii=(0.09, 0.18, 0.28),
        opacities=(0.34, 0.18, 0.08),
        outline_ratio=0.08,
        prefer_fonts=("stxingka", "stxinwei", "sthupo", "simkai"),
        core_shadow=True,
    ),
    "red_impact": _style(
        "血红冲击",
        "#FF1E3C",
        category="hot",
        radii=(0.09, 0.18, 0.28),
        opacities=(0.36, 0.18, 0.08),
        outline_ratio=0.08,
        prefer_fonts=("sthupo", "stxingka", "stxinwei"),
        core_shadow=True,
    ),
    "warm_gold": _style(
        "暖金爆款",
        "#FFB020",
        category="hot",
        radii=(0.08, 0.16, 0.26),
        opacities=(0.32, 0.17, 0.08),
        outline_ratio=0.07,
        outline_color="#2A1600",
        prefer_fonts=("stxinwei", "sthupo", "stxingka"),
        suggest_fill="#FFF6D8",
    ),
    "manga_yellow": _style(
        "漫剧黄字",
        "#FFD400",
        category="hot",
        radii=(0.07, 0.14, 0.22),
        opacities=(0.28, 0.15, 0.07),
        outline_ratio=0.12,
        prefer_fonts=_BOLD_FONTS,
        suggest_fill="#FFE566",
    ),
    "orange_fire": _style(
        "橙火爆款",
        "#FF6A00",
        category="hot",
        radii=(0.09, 0.18, 0.28),
        opacities=(0.34, 0.18, 0.08),
        outline_color="#2A1000",
        prefer_fonts=("sthupo", "stxinwei", "msyhbd"),
        core_shadow=True,
    ),
    "ink_red": _style(
        "朱红国风",
        "#E6392B",
        category="hot",
        radii=(0.08, 0.16, 0.26),
        opacities=(0.32, 0.17, 0.08),
        outline_ratio=0.07,
        prefer_fonts=("stliti", "simli", "stxingka", "fzstk"),
        suggest_fill="#FFF5F2",
        core_shadow=True,
    ),
    "lemon_pop": _style(
        "柠檬爆款",
        "#FFE100",
        category="hot",
        radii=(0.08, 0.16, 0.26),
        opacities=(0.32, 0.17, 0.08),
        outline_color="#3A3200",
        prefer_fonts=_BOLD_FONTS,
        suggest_fill="#FFFCE0",
    ),
    # —— 柔光 ——
    "sunset": _style(
        "日落粉橙",
        "#FF6B9D",
        category="soft",
        radii=(0.08, 0.16, 0.26),
        opacities=(0.30, 0.16, 0.07),
        prefer_fonts=_SOFT_FONTS + _BRUSH_FONTS[:2],
    ),
    "rose_gold": _style(
        "玫瑰金",
        "#FF8FAB",
        category="soft",
        radii=(0.08, 0.16, 0.26),
        opacities=(0.30, 0.16, 0.07),
        suggest_fill="#FFF0F5",
        prefer_fonts=("stcaiyun", "simyou", "stxingka"),
    ),
    "soft_yellow": _style(
        "柔黄标题",
        "#FFE566",
        category="soft",
        radii=(0.08, 0.16, 0.26),
        opacities=(0.28, 0.15, 0.07),
        outline_color="#3A2A00",
        prefer_fonts=("simyou", "stcaiyun", "fzstk"),
        suggest_fill="#FFFCE8",
    ),
    "purple_dream": _style(
        "紫幻柔光",
        "#B44DFF",
        category="soft",
        radii=(0.08, 0.16, 0.26),
        opacities=(0.30, 0.16, 0.07),
        prefer_fonts=("stxingka", "stcaiyun", "fzstk"),
    ),
    # —— 霓虹 / 冷色 ——
    "neon": _style(
        "青霓虹",
        "#00E5FF",
        category="neon",
        radii=(0.07, 0.14, 0.24),
        opacities=(0.30, 0.16, 0.07),
        outline_ratio=0.05,
        outline_color="#001820",
        prefer_fonts=_BOLD_FONTS,
    ),
    "cold_blue": _style(
        "冷蓝情绪",
        "#5B8CFF",
        category="neon",
        prefer_fonts=("stxingka", "stxihei", "msyhbd"),
    ),
    "sky_pop": _style(
        "天空蓝",
        "#4DB8FF",
        category="neon",
        suggest_fill="#F0F8FF",
        prefer_fonts=("msyhbd", "simhei", "stxihei"),
    ),
    "cyan_mint": _style(
        "薄荷绿",
        "#3DFFC8",
        category="neon",
        outline_color="#003528",
        prefer_fonts=("simyou", "msyhbd", "stxihei"),
    ),
    "jade_green": _style(
        "翠绿花字",
        "#2EE59B",
        category="neon",
        outline_color="#003820",
        prefer_fonts=("stxingka", "simyou", "msyhbd"),
        suggest_fill="#F0FFF6",
    ),
    "violet_neon": _style(
        "紫霓虹",
        "#C77DFF",
        category="neon",
        radii=(0.07, 0.14, 0.24),
        opacities=(0.30, 0.16, 0.07),
        outline_color="#1A0030",
        prefer_fonts=_BOLD_FONTS,
    ),
    "deep_purple": _style(
        "深紫悬疑",
        "#7B2FFF",
        category="neon",
        radii=(0.09, 0.18, 0.28),
        opacities=(0.32, 0.17, 0.08),
        prefer_fonts=("stzhongs", "msyhbd", "stxingka"),
        core_shadow=True,
    ),
    "cyber_lime": _style(
        "赛博黄绿",
        "#B8FF00",
        category="neon",
        radii=(0.07, 0.14, 0.24),
        opacities=(0.30, 0.16, 0.07),
        outline_color="#1A2200",
        prefer_fonts=_BOLD_FONTS,
        suggest_fill="#F5FFE8",
    ),
    # —— 纯描边可读 ——
    "outline": _style(
        "黑描边白字",
        "#FFFFFF",
        category="outline",
        radii=(),
        opacities=(),
        steps=0,
        outline_ratio=0.10,
        prefer_fonts=_BOLD_FONTS,
    ),
    "heavy_outline": _style(
        "粗黑描边",
        "#FFFFFF",
        category="outline",
        radii=(),
        opacities=(),
        steps=0,
        outline_ratio=0.16,
        prefer_fonts=_BOLD_FONTS,
    ),
    "gold_stroke": _style(
        "描金大字",
        "#FFD700",
        category="outline",
        radii=(),
        opacities=(),
        steps=0,
        outline_ratio=0.12,
        outline_color="#8B6914",
        prefer_fonts=_BOLD_FONTS,
        suggest_fill="#FFF8DC",
    ),
}


def _register_huazi_effects() -> None:
    """综艺花字注册进统一 effect 表，便于 cfg / 选择器复用。"""
    from app.common.huazi_styles import HUAZI_STYLES

    for sid, hz in HUAZI_STYLES.items():
        _EFFECT_STYLES[sid] = _style(
            hz["label"],
            hz["preview_color"],
            category="huazi",
            radii=(),
            opacities=(),
            steps=0,
            outline_ratio=0.0,
            prefer_fonts=hz["prefer_fonts"],
            suggest_fill=hz["preview_color"],
        )


_register_huazi_effects()

EFFECT_CATEGORY_LABELS: tuple[tuple[str, str], ...] = (
    ("huazi", "综艺花字"),
    ("basic", "基础"),
    ("hot", "热门辉光"),
    ("soft", "柔光"),
    ("neon", "霓虹冷色"),
    ("outline", "描边"),
)

EFFECT_CHOICES: tuple[tuple[str, str], ...] = tuple(
    (eid, style["label"]) for eid, style in _EFFECT_STYLES.items()
)
_EFFECT_DEFAULT_GLOW: dict[str, str] = {
    eid: style["default_glow"] for eid, style in _EFFECT_STYLES.items()
}

DEFAULT_TITLE_PORTRAIT = {
    "x_pct": 1.5,
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
    "x_pct": 1.5,
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
    # 九宫格对齐：c/r/b 成片按实际字宽/块高对齐，避免剧名长短导致「看着居中、成片偏了」
    h_align: str
    v_align: str
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


def _app_base_dir() -> Path:
    if getattr(builtins, "__compiled__", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def bundled_fonts_dir() -> Path:
    return _app_base_dir() / "tools" / "fonts"


def _font_candidate_names(font_key: str) -> tuple[str, ...]:
    key = str(font_key or "").strip().lower()
    primary = font_filename(key) if key in _FONT_BY_KEY else ""
    alts = _FONT_FILE_ALIASES.get(key, ())
    names: list[str] = []
    for name in (primary, *alts):
        n = str(name or "").strip()
        if n and n not in names:
            names.append(n)
    return tuple(names)


def resolve_font_source_path(font_key: str) -> str | None:
    """定位字体文件：tools/fonts → 工程根 → Windows Fonts → 用户 Fonts。"""
    windir = os.environ.get("WINDIR", "C:/Windows")
    local = os.environ.get("LOCALAPPDATA", "")
    search_dirs = [
        bundled_fonts_dir(),
        _app_base_dir(),
        Path(windir) / "Fonts",
        Path(local) / "Microsoft" / "Windows" / "Fonts" if local else None,
    ]
    for name in _font_candidate_names(font_key):
        for directory in search_dirs:
            if directory is None:
                continue
            path = directory / name
            if path.is_file():
                return str(path)
    return None


def available_font_choices() -> list[tuple[str, str, str]]:
    """本机 / 内置目录中实际存在的字体（核心字体始终保留）。"""
    out: list[tuple[str, str, str]] = []
    for key, label, filename in FONT_CHOICES:
        if key in _CORE_FONTS or resolve_font_source_path(key):
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


def effects_in_category(category: str) -> list[tuple[str, str]]:
    """某分组下的 (id, 显示名)，按 _EFFECT_STYLES 声明顺序。"""
    cat = str(category or "").strip().lower()
    return [
        (eid, style["label"])
        for eid, style in _EFFECT_STYLES.items()
        if style.get("category") == cat
    ]


def _soft_glow_offsets(
    effect: TextEffect, fontsize: int
) -> list[tuple[float, float, float]]:
    """柔和辉光副本：(dx, dy, 相对透明度)。

    近缘密采样 + 相邻圈错开角度，避免大半径稀疏叠字造成的重影。
    """
    style = effect_style(effect)
    radii, opacities, steps = style["radii"], style["opacities"], style["steps"]
    if not radii or steps <= 0:
        return []
    out: list[tuple[float, float, float]] = []
    for ring_i, (r_mul, op) in enumerate(zip(radii, opacities)):
        radius = max(1.0, float(fontsize) * float(r_mul))
        # 相邻圈错开半步，减轻圆周「分身」对齐
        ang_offset = (math.pi / steps) * (ring_i % 2)
        for i in range(steps):
            ang = ang_offset + (2.0 * math.pi * i) / steps
            out.append((radius * math.cos(ang), radius * math.sin(ang), op))
    return out


def glow_layer_count(effect: TextEffect | str, fontsize: int = 20) -> int:
    """辉光 drawtext 层数（不含正文），供测试与诊断。"""
    return len(_soft_glow_offsets(clamp_text_effect(effect), fontsize))


def _outline_borderw(effect: TextEffect, fontsize: int) -> int:
    ratio = float(effect_style(effect)["outline_ratio"] or 0.0)
    if ratio <= 0:
        return 0
    return max(1, int(round(fontsize * ratio)))


def effect_label(effect: TextEffect | str) -> str:
    return effect_style(effect)["label"]


def effect_uses_glow(effect: TextEffect | str) -> bool:
    """是否为外发光类（可调发光色）。综艺花字走 PNG，不算发光。"""
    from app.common.huazi_styles import is_huazi_effect

    eid = clamp_text_effect(effect)
    if eid == "none" or is_huazi_effect(eid):
        return False
    style = effect_style(eid)
    return bool(style["radii"] and style["steps"] > 0)


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
        "h_align": clamp_h_align(
            src.get("h_align", defaults_orient.get("h_align", ""))
        ),
        # 垂直始终按 y_pct 字面定位。曾用九宫格把「靠近底部」写成 v_align=b，
        # 导致剧名/提示再次打开时一起贴底重叠；不再持久化垂直几何对齐。
        "v_align": "t",
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


def clamp_h_align(value: Any) -> str:
    key = str(value or "").strip().lower()
    return key if key in ("l", "c", "r") else ""


def clamp_v_align(value: Any) -> str:
    key = str(value or "").strip().lower()
    return key if key in ("t", "c", "b") else ""


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
        "h_align": orient.get("h_align", ""),
        "v_align": orient.get("v_align", ""),
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
    *,
    h_align: str | None = None,
    v_align: str | None = None,
) -> dict:
    key: Orientation = "landscape" if orientation == "landscape" else "portrait"
    out = dict(style)
    cur = dict(out.get(key) if isinstance(out.get(key), dict) else {})
    cur["x_pct"] = _clamp_float(x_pct, 0.0, 100.0, 0.0)
    cur["y_pct"] = _clamp_float(y_pct, 0.0, 100.0, 0.0)
    if h_align is not None:
        cur["h_align"] = clamp_h_align(h_align)
    if v_align is not None:
        cur["v_align"] = clamp_v_align(v_align)
    out[key] = cur
    return out


# 九宫格常用锚点：(水平 l/c/r, 垂直 t/c/b)
POSITION_PRESETS: tuple[tuple[str, str, str, str], ...] = (
    ("tl", "左上", "l", "t"),
    ("tc", "上中", "c", "t"),
    ("tr", "右上", "r", "t"),
    ("ml", "左中", "l", "c"),
    ("mc", "正中", "c", "c"),
    ("mr", "右中", "r", "c"),
    ("bl", "左下", "l", "b"),
    ("bc", "下中", "c", "b"),
    ("br", "右下", "r", "b"),
)
_POSITION_PRESET_BY_ID = {pid: (hx, vy) for pid, _label, hx, vy in POSITION_PRESETS}
_POSITION_GRID: tuple[tuple[str, ...], ...] = (
    ("tl", "tc", "tr"),
    ("ml", "mc", "mr"),
    ("bl", "bc", "br"),
)
_POSITION_CELL: dict[str, tuple[int, int]] = {
    pid: (r, c)
    for r, row in enumerate(_POSITION_GRID)
    for c, pid in enumerate(row)
}
# 九宫格贴边空隙（相对画布短边百分比）；过大时竖排长文视觉会「离边很远」
DEFAULT_POSITION_MARGIN_PCT = 1.5


def pct_for_position_preset(
    preset: str,
    *,
    box_w_ratio: float,
    box_h_ratio: float,
    margin_pct: float = DEFAULT_POSITION_MARGIN_PCT,
) -> tuple[float, float]:
    """按九宫格锚点计算文字左上角百分比。

    box_w_ratio / box_h_ratio 为文字框相对画布宽高的比例（0~1）。
    边缘锚点留 margin_pct 边距；居中锚点按文字框几何中心对齐。
    """
    key = str(preset or "").strip().lower()
    pair = _POSITION_PRESET_BY_ID.get(key)
    if pair is None:
        m = float(DEFAULT_POSITION_MARGIN_PCT)
        return m, m
    hx, vy = pair
    bw = max(0.0, min(1.0, float(box_w_ratio)))
    bh = max(0.0, min(1.0, float(box_h_ratio)))
    m = max(0.0, min(40.0, float(margin_pct))) / 100.0

    if hx == "l":
        x = m
    elif hx == "r":
        x = max(0.0, 1.0 - bw - m)
    else:
        x = max(0.0, (1.0 - bw) / 2.0)

    if vy == "t":
        y = m
    elif vy == "b":
        y = max(0.0, 1.0 - bh - m)
    else:
        y = max(0.0, (1.0 - bh) / 2.0)

    return round(x * 100.0, 2), round(y * 100.0, 2)


def nearest_position_preset(
    x_pct: float,
    y_pct: float,
    *,
    box_w_ratio: float = 0.0,
    box_h_ratio: float = 0.0,
) -> str:
    """根据文字左上角百分比，落到最接近的九宫格格（以文字框中心判格）。"""
    bw = max(0.0, min(1.0, float(box_w_ratio))) * 100.0
    bh = max(0.0, min(1.0, float(box_h_ratio))) * 100.0
    cx = float(x_pct) + bw / 2.0
    cy = float(y_pct) + bh / 2.0
    col = 0 if cx < 100.0 / 3.0 else (2 if cx >= 200.0 / 3.0 else 1)
    row = 0 if cy < 100.0 / 3.0 else (2 if cy >= 200.0 / 3.0 else 1)
    return _POSITION_GRID[row][col]


def step_position_preset(preset: str, *, dcol: int = 0, drow: int = 0) -> str:
    """在九宫格上按列/行偏移一格（越界夹紧）。dcol: -1左/+1右；drow: -1上/+1下。"""
    cell = _POSITION_CELL.get(str(preset or "").strip().lower(), (1, 1))
    row = max(0, min(2, cell[0] + int(drow)))
    col = max(0, min(2, cell[1] + int(dcol)))
    return _POSITION_GRID[row][col]


def align_for_position_preset(preset: str) -> tuple[str, str]:
    """九宫格 id → (h_align, v_align)。"""
    pair = _POSITION_PRESET_BY_ID.get(str(preset or "").strip().lower())
    if pair is None:
        return "l", "t"
    return pair[0], pair[1]


def estimate_overlay_box_ratios(
    text: str,
    fontsize: int,
    *,
    orientation: Orientation = "portrait",
) -> tuple[float, float]:
    """粗估文字框相对画布比例，仅用于旧配置推断对齐。"""
    lines = (text or "").split("\n") or [""]
    n = max(1, len(lines))
    gap = max(0, int(round(float(fontsize) * 0.12)))
    ref_w, ref_h = (1920.0, 1080.0) if orientation == "landscape" else (1080.0, 1920.0)

    def _line_px(s: str) -> float:
        total = 0.0
        for ch in s:
            total += float(fontsize) * (1.0 if ord(ch) > 127 else 0.55)
        return max(float(fontsize) * 0.5, total)

    tw = max((_line_px(line) for line in lines), default=float(fontsize))
    th = float(n * int(fontsize) + max(0, n - 1) * gap)
    return min(0.95, tw / ref_w), min(0.95, th / ref_h)


def resolve_aligns(
    orient: dict,
    *,
    box_w_ratio: float = 0.0,
    box_h_ratio: float = 0.0,
) -> tuple[str, str]:
    """读取 h/v_align；缺省时按文字框中心落入的九宫格推断（兼容旧配置）。"""
    h = clamp_h_align(orient.get("h_align"))
    v = clamp_v_align(orient.get("v_align"))
    if h and v:
        return h, v
    preset = nearest_position_preset(
        float(orient.get("x_pct", 0.0) or 0.0),
        float(orient.get("y_pct", 0.0) or 0.0),
        box_w_ratio=box_w_ratio,
        box_h_ratio=box_h_ratio,
    )
    ih, iv = align_for_position_preset(preset)
    return h or ih, v or iv


def top_left_pct_for_align(
    orient: dict,
    *,
    box_w_ratio: float,
    box_h_ratio: float,
    margin_pct: float = DEFAULT_POSITION_MARGIN_PCT,
) -> tuple[float, float]:
    """按对齐方式计算预览左上角百分比（居中/右随框宽重算）。"""
    v_stored = clamp_v_align(orient.get("v_align"))
    h_align, _v_align = resolve_aligns(
        orient, box_w_ratio=box_w_ratio, box_h_ratio=box_h_ratio
    )
    bw = max(0.0, min(1.0, float(box_w_ratio)))
    bh = max(0.0, min(1.0, float(box_h_ratio)))
    m = max(0.0, min(40.0, float(margin_pct))) / 100.0
    x_pct = _clamp_float(orient.get("x_pct"), 0.0, 100.0, 0.0)
    y_pct = _clamp_float(orient.get("y_pct"), 0.0, 100.0, 0.0)

    # 水平：居中/右对齐始终按框宽算（解决剧名长短偏心）
    if h_align == "c":
        x = (1.0 - bw) / 2.0 * 100.0
    elif h_align == "r":
        x = max(0.0, 1.0 - bw - m) * 100.0
    else:
        x = x_pct

    # 垂直几何对齐仅在显式 v_align 时启用，避免旧配置 y_pct 被误判成贴底
    if v_stored == "c":
        y = (1.0 - bh) / 2.0 * 100.0
    elif v_stored == "b":
        y = max(0.0, 1.0 - bh - m) * 100.0
    else:
        y = y_pct
    return round(x, 2), round(y, 2)


def drawtext_position_exprs(
    orient: dict,
    *,
    line_count: int,
    fontsize: int,
    line_gap: int,
    margin_pct: float = DEFAULT_POSITION_MARGIN_PCT,
    box_w_ratio: float = 0.0,
    box_h_ratio: float = 0.0,
) -> tuple[str, str]:
    """drawtext 的 (x_expr, y0_expr)。水平居中用 text_w，避免剧名长短偏心。"""
    v_stored = clamp_v_align(orient.get("v_align"))
    h_align, _v_align = resolve_aligns(
        orient, box_w_ratio=box_w_ratio, box_h_ratio=box_h_ratio
    )
    m = max(0.0, min(40.0, float(margin_pct))) / 100.0
    x_pct = _clamp_float(orient.get("x_pct"), 0.0, 100.0, 0.0) / 100.0
    y_pct = _clamp_float(orient.get("y_pct"), 0.0, 100.0, 0.0) / 100.0
    n = max(1, int(line_count))
    block = int(n * int(fontsize) + max(0, n - 1) * int(line_gap))

    if h_align == "c":
        x_expr = "(w-text_w)/2"
    elif h_align == "r":
        x_expr = f"w*{1.0 - m:.6f}-text_w"
    else:
        x_expr = f"w*{x_pct:.6f}"

    if v_stored == "c":
        y0 = f"(h-{block})/2"
    elif v_stored == "b":
        y0 = f"h*{1.0 - m:.6f}-{block}"
    else:
        y0 = f"h*{y_pct:.6f}"
    return x_expr, y0


def overlay_image_position_exprs(
    orient: dict,
    *,
    margin_pct: float = DEFAULT_POSITION_MARGIN_PCT,
    box_w_ratio: float = 0.0,
    box_h_ratio: float = 0.0,
) -> tuple[str, str]:
    """ffmpeg overlay 的 (x_expr, y_expr)；主画面 W/H，叠图 w/h。"""
    v_stored = clamp_v_align(orient.get("v_align"))
    h_align, _v_align = resolve_aligns(
        orient, box_w_ratio=box_w_ratio, box_h_ratio=box_h_ratio
    )
    m = max(0.0, min(40.0, float(margin_pct))) / 100.0
    x_pct = _clamp_float(orient.get("x_pct"), 0.0, 100.0, 0.0) / 100.0
    y_pct = _clamp_float(orient.get("y_pct"), 0.0, 100.0, 0.0) / 100.0

    if h_align == "c":
        x_expr = "(W-w)/2"
    elif h_align == "r":
        x_expr = f"W*{1.0 - m:.6f}-w"
    else:
        x_expr = f"W*{x_pct:.6f}"

    if v_stored == "c":
        y_expr = "(H-h)/2"
    elif v_stored == "b":
        y_expr = f"H*{1.0 - m:.6f}-h"
    else:
        y_expr = f"H*{y_pct:.6f}"
    return x_expr, y_expr


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
    no_text: bool


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
    return {
        "selected_id": selected,
        "groups": groups,
        "no_text": bool(lib.get("no_text")),
    }


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
        "no_text": bool(src.get("no_text")),
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
    if clamped.get("no_text"):
        return False
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
    if "export_date_format" in data:
        from app.common.export_paths import clamp_export_date_format

        qconfig.set(
            cfg.clip_export_date_format,
            clamp_export_date_format(data.get("export_date_format")),
        )
    if "export_seq_format" in data:
        from app.common.export_paths import clamp_export_seq_format

        qconfig.set(
            cfg.clip_export_seq_format,
            clamp_export_seq_format(data.get("export_seq_format")),
        )
    if "output_resolution" in data:
        # 成片分辨率：仅接受合法档位，字段缺失/非法不动本地
        from app.data.services.render_service import RESOLUTION_CHOICES

        raw = str(data.get("output_resolution") or "").strip().lower()
        if raw in {v for v, _ in RESOLUTION_CHOICES}:
            qconfig.set(cfg.encode_output_resolution, raw)


def clip_edit_settings_patch(
    *,
    export_name_tag: str | None = None,
    export_date_format: str | None = None,
    export_seq_format: str | None = None,
    overlay_title: dict | None = None,
    overlay_disclaimer: dict | None = None,
    overlay_text_library: dict | None = None,
    output_resolution: str | None = None,
) -> dict:
    clip: dict[str, Any] = {}
    if export_name_tag is not None:
        clip["export_name_tag"] = str(export_name_tag).strip()[:20]
    if export_date_format is not None:
        from app.common.export_paths import clamp_export_date_format

        clip["export_date_format"] = clamp_export_date_format(export_date_format)
    if export_seq_format is not None:
        from app.common.export_paths import clamp_export_seq_format

        clip["export_seq_format"] = clamp_export_seq_format(export_seq_format)
    if output_resolution is not None:
        from app.data.services.render_service import RenderService

        clip["output_resolution"] = RenderService.normalize_render_resolution(
            output_resolution
        )
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


def escape_drawtext_fontfile(path: str) -> str:
    """转义 fontfile= / textfile= 路径（含盘符冒号），并加单引号，避免 filter 链被截断。"""
    p = str(path or "").replace("\\", "/")
    p = p.replace("'", r"\'").replace(":", r"\:")
    return f"'{p}'"


def _ascii_font_cache_dir() -> str:
    """纯 ASCII 字体缓存目录，避免中文工程路径弄坏 drawtext 解析。"""
    d = os.path.join(tempfile.gettempdir(), "AutomatedEditFonts")
    os.makedirs(d, exist_ok=True)
    return d


def _path_has_non_ascii(path: str) -> bool:
    try:
        path.encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


def _text_needs_external_file(text: str) -> bool:
    """非 ASCII 文案不要写进 filter 脚本：Windows 上 FFmpeg 常按系统代码页读脚本导致乱码。"""
    return any(ord(ch) > 127 for ch in (text or ""))


def prepare_drawtext_textfile(text: str) -> str:
    """把文案落到 ASCII 路径的 UTF-8（带 BOM）文件，供 drawtext textfile= 使用。"""
    payload = (text or " ").replace("\r", "").replace("\n", "")
    if not payload:
        payload = " "
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]
    path = os.path.join(_ascii_font_cache_dir(), f"dt_{digest}.txt")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write(payload)
    return path.replace("\\", "/")


def _drawtext_text_option(line: str) -> str:
    raw = line if line else " "
    if _text_needs_external_file(raw):
        return f"textfile={escape_drawtext_fontfile(prepare_drawtext_textfile(raw))}"
    return f"text='{escape_drawtext(raw)}'"


# FFmpeg/FreeType 下无可用汉字轮廓的字体 → 换成同风格可用字体（否则成片变「口口口」）
_DRAWTEXT_FONT_FALLBACKS: dict[str, str] = {
    "simsunb": "simsun",  # Windows simsunb.ttf 在 drawtext 下只有方框
}


def resolve_drawtext_font_key(font_key: str) -> str:
    """成片 drawtext 用的字体 key（含不可用字体回退）。"""
    key = clamp_font_key(font_key)
    return _DRAWTEXT_FONT_FALLBACKS.get(key, key)


def prepare_font_file(font_key: str, work_dir: str | None = None) -> str:
    """确保字体可用，返回供 drawtext fontfile= 使用的**纯 ASCII**路径。

    中文工程缓存路径会导致 FFmpeg 把 ``fontfile=C:/中文/...`` 的盘符冒号
    当成选项分隔符而解析失败；故绝不返回非 ASCII 路径。
    """
    key = resolve_drawtext_font_key(font_key)
    filename = font_filename(key)
    windir = os.environ.get("WINDIR", "C:/Windows")
    resolved = resolve_font_source_path(key)

    # 1) ASCII 临时目录（drawtext 最稳）；缓存名用主文件名，避免中文别名
    ascii_dest = os.path.join(_ascii_font_cache_dir(), filename)
    src_for_ascii = resolved
    if work_dir:
        # 工程缓存里可能是旧的不可用字体副本；回退后文件名已变，按新文件名取
        work_copy = os.path.join(work_dir, filename)
        if os.path.isfile(work_copy):
            src_for_ascii = work_copy
    if src_for_ascii and os.path.isfile(src_for_ascii):
        try:
            # 覆盖拷贝，避免缓存里残留坏文件
            if (not os.path.isfile(ascii_dest)) or (
                os.path.getsize(ascii_dest) != os.path.getsize(src_for_ascii)
            ):
                shutil.copy2(src_for_ascii, ascii_dest)
        except OSError:
            pass
    if os.path.isfile(ascii_dest) and not _path_has_non_ascii(ascii_dest):
        return ascii_dest.replace("\\", "/")

    # 2) 已解析到的源文件（系统 Fonts / tools/fonts，通常为 ASCII）
    if resolved and os.path.isfile(resolved) and not _path_has_non_ascii(resolved):
        return resolved.replace("\\", "/")

    # 3) 工程缓存仅当路径本身是 ASCII 时才用
    if work_dir:
        dest = os.path.join(work_dir, filename)
        if not os.path.isfile(dest) and resolved and os.path.isfile(resolved):
            try:
                shutil.copy2(resolved, dest)
            except OSError:
                pass
        if os.path.isfile(dest) and not _path_has_non_ascii(dest):
            return dest.replace("\\", "/")

    # 4) 最后兜底：微软雅黑（系统几乎必有）
    msyh = os.path.join(windir, "Fonts", font_filename("msyh"))
    if os.path.isfile(msyh):
        ascii_msyh = os.path.join(_ascii_font_cache_dir(), font_filename("msyh"))
        try:
            if not os.path.isfile(ascii_msyh):
                shutil.copy2(msyh, ascii_msyh)
        except OSError:
            pass
        if os.path.isfile(ascii_msyh):
            return ascii_msyh.replace("\\", "/")
        return msyh.replace("\\", "/")
    return filename


def build_drawtext_filters(
    style: OverlayTextStyle | dict,
    *,
    project_name: str,
    fontfile: str | None = None,
    orientation: Orientation = "portrait",
) -> list[str]:
    """生成 drawtext 列表。竖排拆多条；短剧风格=柔光晕 + 细描边正文。

    综艺花字（Pillow PNG）不走 drawtext，返回空列表。
    """
    from app.common.huazi_styles import is_huazi_effect

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
    if is_huazi_effect(orient["effect"]):
        return []
    rendered = apply_text_layout(rendered, orient["layout"])
    # 始终按 key 解析（含 simsunb→simsun）；拒绝中文路径 / 强制回退时忽略传入 fontfile
    font_key = clamp_font_key(orient["font"])
    font = prepare_font_file(font_key)
    if (
        fontfile
        and not _path_has_non_ascii(str(fontfile))
        and resolve_drawtext_font_key(font_key) == font_key
    ):
        # ASCII 绝对路径或单测用的相对文件名
        if os.path.isfile(fontfile) or not os.path.isabs(fontfile):
            font = str(fontfile).replace("\\", "/")
    font_esc = escape_drawtext_fontfile(font)
    color_hex = orient["color"].lstrip("#")
    glow_hex = resolve_glow_color(orient).lstrip("#")
    opacity = orient["opacity"]
    fontsize = orient["fontsize"]
    effect = clamp_text_effect(orient["effect"])
    estyle = effect_style(effect)
    glow_offsets = _soft_glow_offsets(effect, fontsize)
    outline_w = _outline_borderw(effect, fontsize)
    outline_hex = str(estyle["outline_color"]).lstrip("#")
    line_gap = max(0, int(round(fontsize * 0.12)))

    lines = rendered.split("\n")
    est_bw, est_bh = estimate_overlay_box_ratios(
        rendered, fontsize, orientation=orientation
    )
    x_expr, y0 = drawtext_position_exprs(
        orient,
        line_count=len(lines),
        fontsize=fontsize,
        line_gap=line_gap,
        box_w_ratio=est_bw,
        box_h_ratio=est_bh,
    )
    filters: list[str] = []
    for i, line in enumerate(lines):
        text_opt = _drawtext_text_option(line)
        y_expr = y0 if i == 0 else f"{y0}+{i}*({fontsize}+{line_gap})"
        # 1) 柔和外扩光晕（偏移叠字，不是彩色硬描边）
        for dx, dy, op_mul in glow_offsets:
            glow_op = max(0.02, min(1.0, opacity * op_mul))
            x_g = x_expr if abs(dx) < 1e-6 else f"{x_expr}+{dx:.2f}"
            y_g = y_expr if abs(dy) < 1e-6 else f"{y_expr}+{dy:.2f}"
            filters.append(
                f"drawtext=fontfile={font_esc}:{text_opt}:"
                f"x={x_g}:y={y_g}:fontsize={fontsize}:"
                f"fontcolor={glow_hex}@{glow_op:.3f}"
            )
        # 2) 正文：可选细黑描边（短剧标题常用，保证糊底可读）
        core = (
            f"drawtext=fontfile={font_esc}:{text_opt}:"
            f"x={x_expr}:y={y_expr}:fontsize={fontsize}:"
            f"fontcolor={color_hex}@{opacity}"
        )
        if outline_w > 0:
            core += f":borderw={outline_w}:bordercolor={outline_hex}@0.92"
        # 有外发光时不再叠硬阴影，避免「多重重影」
        if estyle["core_shadow"] and not glow_offsets:
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


class OverlayImageSpec(TypedDict):
    path: str
    x_expr: str
    y_expr: str


class OverlayPlan(TypedDict):
    drawtext_filters: list[str]
    image_overlays: list[OverlayImageSpec]


def _build_huazi_image_spec(
    style: OverlayTextStyle | dict,
    *,
    project_name: str,
    orientation: Orientation,
    cache_dir: str | None,
) -> OverlayImageSpec | None:
    from app.common.huazi_render import render_huazi_png_file
    from app.common.huazi_styles import is_huazi_effect

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
        return None
    orient = position_for_orientation(s, orientation)
    if not is_huazi_effect(orient["effect"]):
        return None
    layout_text = apply_text_layout(rendered, orient["layout"])
    font_path = prepare_font_file(orient["font"], work_dir=cache_dir)
    # prepare_font_file 可能返回相对文件名；渲染需要可读绝对/存在路径
    if not os.path.isfile(font_path):
        resolved = resolve_font_source_path(orient["font"])
        if resolved and os.path.isfile(resolved):
            font_path = resolved
    try:
        png = render_huazi_png_file(
            layout_text,
            orient["effect"],
            font_path=font_path,
            fontsize=int(orient["fontsize"]),
            opacity=float(orient["opacity"]),
            cache_dir=cache_dir,
        )
    except Exception:
        return None
    est_bw, est_bh = estimate_overlay_box_ratios(
        layout_text, int(orient["fontsize"]), orientation=orientation
    )
    x_expr, y_expr = overlay_image_position_exprs(
        orient, box_w_ratio=est_bw, box_h_ratio=est_bh
    )
    return {"path": png.replace("\\", "/"), "x_expr": x_expr, "y_expr": y_expr}


def overlay_text_disabled_from_cfg() -> bool:
    """画面文字弹框「不设置文字」打开时为 True。"""
    from app.common.config import cfg

    raw = _parse_json_cfg(cfg.overlay_text_library_json.value)
    if not isinstance(raw, dict):
        return False
    return bool(raw.get("no_text"))


# 叠字 fontsize 的基准画布高度：设置里的字号按 720p 观感配置
OVERLAY_FONT_BASE_CANVAS_H = 720


def overlay_font_scale(canvas_h: int | None) -> float:
    """成片画布高度 → fontsize 缩放系数；非 720p 输出时等比缩放。"""
    try:
        h = int(canvas_h) if canvas_h is not None else 0
    except (TypeError, ValueError):
        return 1.0
    if h <= 0 or h == OVERLAY_FONT_BASE_CANVAS_H:
        return 1.0
    return max(0.5, h / OVERLAY_FONT_BASE_CANVAS_H)


def _scale_style_fontsize(style: OverlayTextStyle | dict, scale: float) -> dict:
    """复制 style 并按系数缩放 fontsize（含 portrait/landscape 子桶，
    供非 720p 成片保持观感同比）。"""
    if scale == 1.0:
        return dict(style)
    scaled = dict(style)
    try:
        fs = int(round(float(scaled.get("fontsize") or 0) * scale))
    except (TypeError, ValueError):
        return scaled
    if fs > 0:
        scaled["fontsize"] = fs
    for key in ("portrait", "landscape"):
        sub = scaled.get(key)
        if not isinstance(sub, dict):
            continue
        sub2 = dict(sub)
        try:
            sfs = int(round(float(sub2.get("fontsize") or 0) * scale))
        except (TypeError, ValueError):
            continue
        if sfs > 0:
            sub2["fontsize"] = sfs
        scaled[key] = sub2
    return scaled


def build_overlay_plan(
    project_name: str,
    *,
    horizontal: bool = False,
    cache_dir: str | None = None,
    canvas_h: int | None = None,
) -> OverlayPlan:
    """生成成片叠字计划：drawtext 链 + 综艺花字 PNG overlay。

    canvas_h：成片画布高度（如 1080）。叠字 fontsize 按 720p 基准配置，
    输出其他分辨率时按 canvas_h/720 等比缩放（drawtext 与花字 PNG 同步），
    保证与预览观感一致；缺省不缩放（兼容旧调用）。缩放后仍受
    clamp_overlay_fontsize 上限约束。
    """
    if overlay_text_disabled_from_cfg():
        return {"drawtext_filters": [], "image_overlays": []}
    orientation: Orientation = "landscape" if horizontal else "portrait"
    scale = overlay_font_scale(canvas_h)
    title = _scale_style_fontsize(load_overlay_title_from_cfg(), scale)
    disc = _scale_style_fontsize(load_overlay_disclaimer_from_cfg(), scale)
    fonts_needed: set[str] = set()
    for style in (title, disc):
        if not resolve_overlay_text(style["text"], project_name).strip():
            continue
        fonts_needed.add(position_for_orientation(style, orientation)["font"])
    fontfiles = {k: prepare_font_file(k, work_dir=cache_dir) for k in fonts_needed}

    drawtext: list[str] = []
    images: list[OverlayImageSpec] = []
    for style in (title, disc):
        orient = position_for_orientation(style, orientation)
        fontfile = fontfiles.get(orient["font"])
        drawtext.extend(
            build_drawtext_filters(
                style,
                project_name=project_name,
                fontfile=fontfile,
                orientation=orientation,
            )
        )
        spec = _build_huazi_image_spec(
            style,
            project_name=project_name,
            orientation=orientation,
            cache_dir=cache_dir,
        )
        if spec is not None:
            images.append(spec)
    return {"drawtext_filters": drawtext, "image_overlays": images}


def build_overlay_drawtext_filters(
    project_name: str, *, horizontal: bool = False
) -> list[str]:
    """按当前 cfg 生成剧名+提示的 drawtext 列表（空文案跳过）。

    兼容旧调用；综艺花字请用 build_overlay_plan。
    """
    return build_overlay_plan(project_name, horizontal=horizontal)["drawtext_filters"]
