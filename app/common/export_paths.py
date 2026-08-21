import datetime
import os
import re
from pathlib import Path
from typing import Any

from app.common.config import cfg

DEFAULT_EXPORT_FOLDER = "剪辑输出"

DEFAULT_EXPORT_DATE_FORMAT = "md"
DEFAULT_EXPORT_SEQ_FORMAT = "pad2"

# value, 下拉显示（含示例）
EXPORT_DATE_FORMAT_CHOICES: tuple[tuple[str, str], ...] = (
    ("md", "月日（0819）"),
    ("ymd", "年月日（20260819）"),
    ("ymd_dash", "年-月-日（2026-08-19）"),
    ("none", "不显示日期"),
)
EXPORT_SEQ_FORMAT_CHOICES: tuple[tuple[str, str], ...] = (
    ("pad2", "01、02、03"),
    ("plain", "1、2、3"),
    ("paren_pad2", "(01)、(02)、(03)"),
    ("paren_plain", "(1)、(2)、(3)"),
    ("pad3", "001、002、003"),
)
_DATE_FORMATS = {k for k, _ in EXPORT_DATE_FORMAT_CHOICES}
_SEQ_FORMATS = {k for k, _ in EXPORT_SEQ_FORMAT_CHOICES}


def resolve_clip_export_root() -> str:
    custom = cfg.clip_export_dir.value.strip()
    if custom:
        return custom
    return str(Path.home() / "Desktop" / DEFAULT_EXPORT_FOLDER)


def resolve_project_export_dir(project_name: str) -> str:
    root = resolve_clip_export_root()
    safe_name = _sanitize_dir_name(project_name)
    path = os.path.join(root, safe_name)
    os.makedirs(path, exist_ok=True)
    return path


def _sanitize_name_part(name: str, *, fallback: str = "未命名") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", name.strip())
    return cleaned or fallback


def _sanitize_dir_name(name: str) -> str:
    return _sanitize_name_part(name, fallback="未命名剧目")


def clamp_export_date_format(value: Any) -> str:
    s = str(value or "").strip()
    return s if s in _DATE_FORMATS else DEFAULT_EXPORT_DATE_FORMAT


def clamp_export_seq_format(value: Any) -> str:
    s = str(value or "").strip()
    return s if s in _SEQ_FORMATS else DEFAULT_EXPORT_SEQ_FORMAT


def format_export_date(
    when: datetime.datetime,
    date_format: str | None = None,
) -> str:
    fmt = clamp_export_date_format(date_format)
    if fmt == "ymd":
        return when.strftime("%Y%m%d")
    if fmt == "ymd_dash":
        return when.strftime("%Y-%m-%d")
    if fmt == "none":
        return ""
    return when.strftime("%m%d")


def format_export_sequence(sequence: int, seq_format: str | None = None) -> str:
    seq = max(int(sequence), 0)
    fmt = clamp_export_seq_format(seq_format)
    if fmt in ("plain", "paren_plain"):
        body = str(seq)
    elif fmt == "pad3":
        body = f"{seq:03d}"
    else:
        body = f"{seq:02d}"
    if fmt.startswith("paren"):
        return f"({body})"
    return body


def build_clip_export_filename(
    project_name: str,
    sequence: int,
    *,
    when: datetime.datetime | None = None,
    tag: str | None = None,
    date_format: str | None = None,
    seq_format: str | None = None,
) -> str:
    """生成导出视频文件名（不含扩展名）：剧名-标识-日期-序号。"""
    date_fmt = (
        clamp_export_date_format(date_format)
        if date_format is not None
        else clamp_export_date_format(cfg.clip_export_date_format.value)
    )
    seq_fmt = (
        clamp_export_seq_format(seq_format)
        if seq_format is not None
        else clamp_export_seq_format(cfg.clip_export_seq_format.value)
    )
    date_str = format_export_date(when or datetime.datetime.now(), date_fmt)
    parts = [_sanitize_name_part(project_name, fallback="未命名剧目")]
    tag = cfg.clip_export_name_tag.value.strip() if tag is None else tag.strip()
    if tag:
        safe_tag = _sanitize_name_part(tag, fallback="")
        if safe_tag:
            parts.append(safe_tag)
    if date_str:
        parts.append(date_str)
    parts.append(format_export_sequence(sequence, seq_fmt))
    return "-".join(parts)
