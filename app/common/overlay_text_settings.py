"""渲染画面叠字（剧名 / 提示）设置：默认值、clamp、drawtext 生成、cfg 读写。"""

from __future__ import annotations

import json
import os
import shutil
from typing import Any, Literal, TypedDict

Orientation = Literal["portrait", "landscape"]
TextLayout = Literal["horizontal", "vertical"]

# 字体 key -> (显示名, Windows Fonts 文件名)
FONT_CHOICES: tuple[tuple[str, str, str], ...] = (
    ("msyh", "微软雅黑", "msyh.ttc"),
    ("simhei", "黑体", "simhei.ttf"),
    ("simsun", "宋体", "simsun.ttc"),
    ("simkai", "楷体", "simkai.ttf"),
    ("msyhbd", "微软雅黑粗体", "msyhbd.ttc"),
)

_FONT_BY_KEY = {k: (label, filename) for k, label, filename in FONT_CHOICES}
DEFAULT_FONT = "msyh"

DEFAULT_TITLE_PORTRAIT = {"x_pct": 4.0, "y_pct": 94.5}
DEFAULT_TITLE_LANDSCAPE = {"x_pct": 2.5, "y_pct": 90.0}
DEFAULT_DISCLAIMER_PORTRAIT = {"x_pct": 4.0, "y_pct": 96.9}
DEFAULT_DISCLAIMER_LANDSCAPE = {"x_pct": 2.5, "y_pct": 94.0}

DEFAULT_TITLE: dict[str, Any] = {
    "text": "《{name}》",
    "font": DEFAULT_FONT,
    "fontsize": 22,
    "color": "#FFFFFF",
    "opacity": 0.8,
    "layout": "horizontal",
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
    "portrait": dict(DEFAULT_DISCLAIMER_PORTRAIT),
    "landscape": dict(DEFAULT_DISCLAIMER_LANDSCAPE),
}


class OverlayPos(TypedDict):
    x_pct: float
    y_pct: float


class OverlayTextStyle(TypedDict):
    text: str
    font: str
    fontsize: int
    color: str
    opacity: float
    layout: TextLayout
    portrait: OverlayPos
    landscape: OverlayPos


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


def _clamp_pos(data: Any, defaults: dict[str, float]) -> OverlayPos:
    src = data if isinstance(data, dict) else {}
    return {
        "x_pct": _clamp_float(src.get("x_pct"), 0.0, 100.0, float(defaults["x_pct"])),
        "y_pct": _clamp_float(src.get("y_pct"), 0.0, 100.0, float(defaults["y_pct"])),
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
    }
    def_landscape = defaults.get("landscape") or dict(def_portrait)

    # 旧扁平 x_pct/y_pct → portrait；landscape 用 defaults.landscape
    if isinstance(src.get("portrait"), dict):
        portrait = _clamp_pos(src["portrait"], def_portrait)
    elif "x_pct" in src or "y_pct" in src:
        portrait = _clamp_pos(
            {"x_pct": src.get("x_pct"), "y_pct": src.get("y_pct")},
            def_portrait,
        )
    else:
        portrait = _clamp_pos(None, def_portrait)

    if isinstance(src.get("landscape"), dict):
        landscape = _clamp_pos(src["landscape"], def_landscape)
    else:
        landscape = _clamp_pos(None, def_landscape)

    layout = clamp_text_layout(
        src.get("layout", defaults.get("layout", "horizontal"))
    )

    return {
        "text": text,
        "font": clamp_font_key(src.get("font", defaults["font"])),
        "fontsize": _clamp_int(
            src.get("fontsize"), 8, 200, int(defaults["fontsize"])
        ),
        "color": _normalize_color(src.get("color"), str(defaults["color"])),
        "opacity": _clamp_float(
            src.get("opacity"), 0.0, 1.0, float(defaults["opacity"])
        ),
        "layout": layout,
        "portrait": portrait,
        "landscape": landscape,
    }


def position_for_orientation(
    style: OverlayTextStyle | dict, orientation: Orientation
) -> OverlayPos:
    key: Orientation = "landscape" if orientation == "landscape" else "portrait"
    pos = style.get(key) if isinstance(style, dict) else None
    if isinstance(pos, dict) and "x_pct" in pos and "y_pct" in pos:
        return {"x_pct": float(pos["x_pct"]), "y_pct": float(pos["y_pct"])}
    # 兼容未迁移的扁平字段
    return {
        "x_pct": float(style.get("x_pct", 0.0)),  # type: ignore[arg-type]
        "y_pct": float(style.get("y_pct", 0.0)),  # type: ignore[arg-type]
    }


def set_position_for_orientation(
    style: dict,
    orientation: Orientation,
    x_pct: float,
    y_pct: float,
) -> dict:
    key: Orientation = "landscape" if orientation == "landscape" else "portrait"
    out = dict(style)
    out[key] = {
        "x_pct": _clamp_float(x_pct, 0.0, 100.0, 0.0),
        "y_pct": _clamp_float(y_pct, 0.0, 100.0, 0.0),
    }
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


def load_overlay_title_from_cfg() -> OverlayTextStyle:
    from app.common.config import cfg

    return clamp_overlay_style(_parse_json_cfg(cfg.overlay_title_json.value), DEFAULT_TITLE)


def load_overlay_disclaimer_from_cfg() -> OverlayTextStyle:
    from app.common.config import cfg

    return clamp_overlay_style(
        _parse_json_cfg(cfg.overlay_disclaimer_json.value), DEFAULT_DISCLAIMER
    )


def save_overlay_styles_to_cfg(
    title: dict | OverlayTextStyle,
    disclaimer: dict | OverlayTextStyle,
) -> tuple[OverlayTextStyle, OverlayTextStyle]:
    from qfluentwidgets import qconfig

    from app.common.config import cfg

    title_c = clamp_overlay_style(dict(title), DEFAULT_TITLE)
    disc_c = clamp_overlay_style(dict(disclaimer), DEFAULT_DISCLAIMER)
    qconfig.set(cfg.overlay_title_json, json.dumps(title_c, ensure_ascii=False))
    qconfig.set(cfg.overlay_disclaimer_json, json.dumps(disc_c, ensure_ascii=False))
    return title_c, disc_c


def apply_overlay_from_clip_edit_dict(data: dict | None) -> None:
    """从服务端 clip_edit 命名空间写入本地 cfg（含 export_name_tag 与叠字）。"""
    if not data:
        return
    from qfluentwidgets import qconfig

    from app.common.config import cfg

    if data.get("overlay_title") is not None:
        title = clamp_overlay_style(data.get("overlay_title"), DEFAULT_TITLE)
        qconfig.set(cfg.overlay_title_json, json.dumps(title, ensure_ascii=False))
    if data.get("overlay_disclaimer") is not None:
        disc = clamp_overlay_style(data.get("overlay_disclaimer"), DEFAULT_DISCLAIMER)
        qconfig.set(cfg.overlay_disclaimer_json, json.dumps(disc, ensure_ascii=False))
    if "export_name_tag" in data:
        qconfig.set(
            cfg.clip_export_name_tag,
            str(data.get("export_name_tag") or "").strip()[:64],
        )


def clip_edit_settings_patch(
    *,
    export_name_tag: str | None = None,
    overlay_title: dict | None = None,
    overlay_disclaimer: dict | None = None,
) -> dict:
    clip: dict[str, Any] = {}
    if export_name_tag is not None:
        clip["export_name_tag"] = str(export_name_tag).strip()[:64]
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
    """转义 FFmpeg drawtext 的 text= 单引号包裹内容。"""
    out = text.replace("\\", "\\\\")
    out = out.replace("'", r"\'")
    out = out.replace(":", r"\:")
    out = out.replace("%", "%%")
    # 换行写成 \n，避免 filter_complex 被真实换行拆断
    out = out.replace("\r\n", "\n").replace("\r", "\n").replace("\n", r"\n")
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


def build_drawtext_filter(
    style: OverlayTextStyle | dict,
    *,
    project_name: str,
    fontfile: str | None = None,
    orientation: Orientation = "portrait",
) -> str | None:
    """生成单条 drawtext filter；解析后文案为空则返回 None。"""
    defaults = {
        "text": "",
        "font": DEFAULT_FONT,
        "fontsize": 16,
        "color": "#FFFFFF",
        "opacity": 1.0,
        "layout": "horizontal",
        "portrait": {"x_pct": 0.0, "y_pct": 0.0},
        "landscape": {"x_pct": 0.0, "y_pct": 0.0},
    }
    s = clamp_overlay_style(dict(style), defaults)
    rendered = resolve_overlay_text(s["text"], project_name)
    if not rendered.strip():
        return None
    rendered = apply_text_layout(rendered, s["layout"])
    pos = position_for_orientation(s, orientation)
    font = fontfile or prepare_font_file(s["font"])
    font_esc = font.replace("\\", "/").replace(":", r"\:")
    color_hex = s["color"].lstrip("#")
    opacity = s["opacity"]
    x_expr = f"w*{pos['x_pct'] / 100.0:.6f}"
    y_expr = f"h*{pos['y_pct'] / 100.0:.6f}"
    text_esc = escape_drawtext(rendered)
    return (
        f"drawtext=fontfile={font_esc}:text='{text_esc}':"
        f"x={x_expr}:y={y_expr}:fontsize={s['fontsize']}:"
        f"fontcolor={color_hex}@{opacity}"
    )


def build_overlay_drawtext_filters(
    project_name: str, *, horizontal: bool = False
) -> list[str]:
    """按当前 cfg 生成剧名+提示的 drawtext 列表（空文案跳过）。"""
    orientation: Orientation = "landscape" if horizontal else "portrait"
    title = load_overlay_title_from_cfg()
    disc = load_overlay_disclaimer_from_cfg()
    fonts_needed: set[str] = set()
    if resolve_overlay_text(title["text"], project_name).strip():
        fonts_needed.add(title["font"])
    if resolve_overlay_text(disc["text"], project_name).strip():
        fonts_needed.add(disc["font"])
    fontfiles = {k: prepare_font_file(k) for k in fonts_needed}

    filters: list[str] = []
    title_f = build_drawtext_filter(
        title,
        project_name=project_name,
        fontfile=fontfiles.get(title["font"]),
        orientation=orientation,
    )
    if title_f:
        filters.append(title_f)
    disc_f = build_drawtext_filter(
        disc,
        project_name=project_name,
        fontfile=fontfiles.get(disc["font"]),
        orientation=orientation,
    )
    if disc_f:
        filters.append(disc_f)
    return filters
