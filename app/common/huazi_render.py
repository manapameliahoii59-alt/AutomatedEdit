"""Pillow 预渲综艺花字 → 透明 PNG（多层描边/渐变/发光）。"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from functools import lru_cache
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.common.huazi_styles import (
    HUAZI_STYLES,
    HuaziLayer,
    HuaziStyle,
    get_huazi_style,
    is_huazi_effect,
)


def _parse_color(raw: str, opacity: float = 1.0) -> tuple[int, int, int, int]:
    s = str(raw or "#FFFFFF").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        s = "FFFFFF"
    r = int(s[0:2], 16)
    g = int(s[2:4], 16)
    b = int(s[4:6], 16)
    a = max(0, min(255, int(round(255 * max(0.0, min(1.0, opacity))))))
    return r, g, b, a


@lru_cache(maxsize=32)
def _load_font(font_path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(font_path, size=max(8, int(size)))
    except OSError:
        return ImageFont.load_default()


def _text_bbox(
    text: str, font: ImageFont.ImageFont, *, spacing: int
) -> tuple[int, int, int, int]:
    tmp = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tmp)
    return draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing)


def _vertical_gradient(
    size: tuple[int, int], c1: str, c2: str, opacity: float = 1.0
) -> Image.Image:
    w, h = size
    top = _parse_color(c1, opacity)
    bot = _parse_color(c2, opacity)
    img = Image.new("RGBA", (w, h))
    px = img.load()
    if h <= 1:
        for x in range(w):
            px[x, 0] = top
        return img
    for y in range(h):
        t = y / (h - 1)
        rgba = tuple(int(top[i] * (1 - t) + bot[i] * t) for i in range(4))
        for x in range(w):
            px[x, y] = rgba  # type: ignore[assignment]
    return img


def _draw_multiline(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.ImageFont,
    *,
    fill: tuple[int, int, int, int],
    spacing: int,
    stroke_width: int = 0,
    stroke_fill: tuple[int, int, int, int] | None = None,
) -> None:
    kwargs: dict[str, Any] = {
        "font": font,
        "fill": fill,
        "spacing": spacing,
    }
    if stroke_width > 0 and stroke_fill is not None:
        kwargs["stroke_width"] = stroke_width
        kwargs["stroke_fill"] = stroke_fill
    draw.multiline_text(xy, text, **kwargs)


def render_huazi_image(
    text: str,
    style: HuaziStyle | str,
    *,
    font_path: str,
    fontsize: int,
    opacity: float = 1.0,
) -> Image.Image:
    """把文案渲成透明 RGBA 图（含描边/发光内边距）。"""
    raw = (text or "").replace("\r", "")
    if not raw.strip():
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))

    if isinstance(style, str):
        resolved = get_huazi_style(style)
        if resolved is None:
            raise ValueError(f"未知花字样式: {style}")
        style = resolved

    fs = max(12, int(fontsize))
    font = _load_font(font_path, fs)
    spacing = max(0, int(round(fs * 0.12)))

    # 预估外扩：描边 + 发光 + 阴影偏移
    pad = int(round(fs * 0.85))
    bbox = _text_bbox(raw, font, spacing=spacing)
    tw = max(1, bbox[2] - bbox[0])
    th = max(1, bbox[3] - bbox[1])
    canvas_w = tw + pad * 2
    canvas_h = th + pad * 2
    origin = (pad - bbox[0], pad - bbox[1])

    base = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    op = max(0.05, min(1.0, float(opacity)))

    for layer in style["layers"]:
        kind = str(layer.get("kind") or "")
        layer_op = float(layer.get("opacity") or 1.0) * op
        dx = float(layer.get("dx") or 0.0) * fs
        dy = float(layer.get("dy") or 0.0) * fs
        width = float(layer.get("width") or 0.0) * fs
        blur = float(layer.get("blur") or 0.0) * fs
        xy = (origin[0] + dx, origin[1] + dy)

        if kind == "glow":
            color = _parse_color(str(layer.get("color") or "#FFFFFF"), layer_op)
            tmp = Image.new("RGBA", base.size, (0, 0, 0, 0))
            td = ImageDraw.Draw(tmp)
            stroke_w = max(0, int(round(width))) if width > 0 else max(1, int(round(fs * 0.06)))
            _draw_multiline(
                td,
                (origin[0], origin[1]),
                raw,
                font,
                fill=color,
                spacing=spacing,
                stroke_width=stroke_w,
                stroke_fill=color,
            )
            radius = max(1, int(round(blur)))
            tmp = tmp.filter(ImageFilter.GaussianBlur(radius=radius))
            base.alpha_composite(tmp)
            continue

        if kind == "shadow":
            color = _parse_color(str(layer.get("color") or "#000000"), layer_op)
            stroke_w = max(0, int(round(width)))
            draw = ImageDraw.Draw(base)
            _draw_multiline(
                draw,
                xy,
                raw,
                font,
                fill=color,
                spacing=spacing,
                stroke_width=stroke_w,
                stroke_fill=color if stroke_w > 0 else None,
            )
            continue

        if kind == "stroke":
            color = _parse_color(str(layer.get("color") or "#FFFFFF"), layer_op)
            stroke_w = max(1, int(round(width)))
            draw = ImageDraw.Draw(base)
            # 透明填充 + 描边，避免盖住下层
            _draw_multiline(
                draw,
                (origin[0], origin[1]),
                raw,
                font,
                fill=(0, 0, 0, 0),
                spacing=spacing,
                stroke_width=stroke_w,
                stroke_fill=color,
            )
            continue

        if kind == "fill":
            color = _parse_color(str(layer.get("color") or "#FFFFFF"), layer_op)
            draw = ImageDraw.Draw(base)
            _draw_multiline(
                draw,
                (origin[0], origin[1]),
                raw,
                font,
                fill=color,
                spacing=spacing,
            )
            continue

        if kind == "fill_gradient":
            colors = layer.get("colors") or ("#FFFFFF", "#CCCCCC")
            c1, c2 = colors[0], colors[1] if len(colors) > 1 else colors[0]
            mask = Image.new("L", base.size, 0)
            md = ImageDraw.Draw(mask)
            _draw_multiline(
                md,
                (origin[0], origin[1]),
                raw,
                font,
                fill=255,
                spacing=spacing,
            )
            grad = _vertical_gradient(base.size, str(c1), str(c2), layer_op)
            colored = Image.new("RGBA", base.size, (0, 0, 0, 0))
            colored.paste(grad, mask=mask)
            base.alpha_composite(colored)
            continue

    return base


def render_huazi_png_file(
    text: str,
    style_id: str,
    *,
    font_path: str,
    fontsize: int,
    opacity: float = 1.0,
    cache_dir: str | None = None,
) -> str:
    """渲染并落盘 PNG，返回路径（同参数复用缓存文件）。"""
    style = get_huazi_style(style_id)
    if style is None:
        raise ValueError(f"未知花字样式: {style_id}")

    key_src = "|".join(
        [
            style_id,
            text,
            font_path,
            str(int(fontsize)),
            f"{float(opacity):.3f}",
        ]
    )
    digest = hashlib.sha1(key_src.encode("utf-8")).hexdigest()[:16]
    out_dir = cache_dir or tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"huazi_{digest}.png")
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return path

    img = render_huazi_image(
        text,
        style,
        font_path=font_path,
        fontsize=fontsize,
        opacity=opacity,
    )
    tmp_path = path + ".tmp"
    img.save(tmp_path, format="PNG")
    os.replace(tmp_path, path)
    return path


def list_huazi_styles() -> list[HuaziStyle]:
    return list(HUAZI_STYLES.values())


# 提示文字局部变色：书名号竖排变换（与 apply_text_layout 同规则）
_RICH_VERTICAL_MARKS = str.maketrans({"《": "︽", "》": "︾"})


def _resolve_span_colors(
    text: str,
    spans: list[dict] | None,
    base_rgba: tuple[int, int, int, int],
) -> tuple[str, list[tuple[int, int, int, int]]]:
    """按「追加变色段」生成成片文字与逐字颜色。

    变色文字按声明顺序拼接在文案末尾（不再要求与文案匹配），
    各段整体用各自颜色；返回 (组合后完整文案, 逐字颜色)。
    """
    parts: list[tuple[str, tuple[int, int, int, int]]] = [(text, base_rgba)]
    for span in spans or []:
        if not isinstance(span, dict):
            continue
        sub = str(span.get("text") or "").replace("\r", "")
        if not sub:
            continue
        rgba = _parse_color(str(span.get("color") or "#FFFF00"), base_rgba[3] / 255.0)
        parts.append((sub, rgba))
    combined = "".join(p for p, _ in parts)
    colors: list[tuple[int, int, int, int]] = []
    for piece, rgba in parts:
        colors.extend([rgba] * len(piece))
    return combined, colors


def render_rich_text_image(
    text: str,
    spans: list[dict] | None,
    *,
    font_path: str,
    fontsize: int,
    color: str = "#FFFFFF",
    opacity: float = 1.0,
    layout: str = "horizontal",
    line_pitch: float | None = None,
) -> Image.Image:
    """局部变色富文本 → 透明 RGBA。

    文案 + 变色文字（按顺序拼接在文案后）逐段染色。
    横排：同色连续字符合并为一段绘制（字符逐个计量推进）；
    竖排：逐字下排、每字独立着色（空格→全角空格、书名号→竖式，1:1 变换）。
    line_pitch：竖排行步进像素；缺省用 fontsize + 0.12*fontsize（与成片
    drawtext 竖排步进一致），预览可传入自身行距以保持加规则前后布局不变。
    """
    raw, colors = _resolve_span_colors(
        (text or "").replace("\r", ""), spans, _parse_color(color, opacity)
    )
    fs = max(8, int(fontsize))
    font = _load_font(font_path, fs)
    spacing = max(0, int(round(fs * 0.12)))
    vertical = str(layout or "").strip().lower() == "vertical"
    measure = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    pad = 2
    pitch = float(line_pitch) if line_pitch and line_pitch > 0 else (fs + spacing)
    ascent, descent = font.getmetrics()
    line_h = max(1, ascent + descent)

    if vertical:
        seq = [
            ("　" if ch == " " else ch.translate(_RICH_VERTICAL_MARKS))
            for ch in raw
        ]
        widths = [
            max(1, int(round(measure.textlength(ch if ch.strip() else "　", font=font))))
            for ch in seq
        ]
        n = max(1, len(seq))
        w = max(widths) + pad * 2
        # pitch 可能为浮点（预览传入 Qt lineSpacing），画布尺寸必须取整
        h = int(round(n * pitch)) + pad * 2
        img = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        y = float(pad)
        for ch, cw, rgba in zip(seq, widths, colors):
            if ch.strip():
                d.text((pad + (max(widths) - cw) / 2.0, y), ch, font=font, fill=rgba)
            y += pitch
        return img

    # 横排：同色连续字符合并为一段
    w = int(round(sum(measure.textlength(ch, font=font) for ch in raw))) + pad * 2
    h = line_h + pad * 2
    img = Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    runs: list[tuple[float, str, tuple[int, int, int, int]]] = []
    x = float(pad)
    cur_text = ""
    cur_rgba: tuple[int, int, int, int] | None = None
    for ch, rgba in zip(raw, colors):
        if cur_rgba is None:
            cur_rgba = rgba
        if rgba != cur_rgba:
            runs.append((x, cur_text, cur_rgba))
            x += sum(measure.textlength(c, font=font) for c in cur_text)
            cur_text = ""
            cur_rgba = rgba
        cur_text += ch
    if cur_text:
        runs.append((x, cur_text, cur_rgba))
    for rx, rtext, rrgba in runs:
        d.text((rx, pad), rtext, font=font, fill=rrgba)
    return img


def render_rich_text_png_file(
    text: str,
    spans: list[dict],
    *,
    font_path: str,
    fontsize: int,
    color: str = "#FFFFFF",
    opacity: float = 1.0,
    layout: str = "horizontal",
    line_pitch: float | None = None,
    cache_dir: str | None = None,
) -> str:
    """渲染局部变色富文本并落盘 PNG，返回路径（同参数复用缓存文件）。"""
    key_src = "|".join(
        [
            "rich",
            text,
            json.dumps(spans, ensure_ascii=False, sort_keys=True),
            font_path,
            str(int(fontsize)),
            f"{float(opacity):.3f}",
            layout,
            "" if line_pitch is None else f"{float(line_pitch):.2f}",
        ]
    )
    digest = hashlib.sha1(key_src.encode("utf-8")).hexdigest()[:16]
    out_dir = cache_dir or tempfile.gettempdir()
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"rich_{digest}.png")
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return path

    img = render_rich_text_image(
        text,
        spans,
        font_path=font_path,
        fontsize=fontsize,
        color=color,
        opacity=opacity,
        layout=layout,
        line_pitch=line_pitch,
    )
    tmp_path = path + ".tmp"
    img.save(tmp_path, format="PNG")
    os.replace(tmp_path, path)
    return path


__all__ = [
    "is_huazi_effect",
    "render_huazi_image",
    "render_huazi_png_file",
    "render_rich_text_image",
    "render_rich_text_png_file",
    "list_huazi_styles",
]
