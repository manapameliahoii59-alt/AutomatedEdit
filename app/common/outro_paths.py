"""片尾素材：内置默认 + 多条目自定义库（横/竖屏分开，可勾选启用）。"""

from __future__ import annotations

import builtins
import json
import re
import shutil
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.common.ffmpeg_paths import resolve_ffmpeg, resolve_ffprobe
from app.common.win_subprocess import run as win_run

OrientationKey = Literal["landscape", "portrait"]

_OUTRO_REL = Path("tools") / "outro"
_CUSTOM_REL = _OUTRO_REL / "custom"
_MANIFEST_NAME = "library.json"

HORIZONTAL_OUTRO = "横屏结尾.mp4"
VERTICAL_OUTRO = "竖屏结尾.mp4"

# 兼容旧版单文件自定义
_LEGACY_CUSTOM = {
    "landscape": "landscape.mp4",
    "portrait": "portrait.mp4",
}

_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}
_THUMB_SIZE = 160  # 最长边像素


@dataclass(frozen=True)
class OutroItem:
    id: str
    name: str
    width: int
    height: int
    video_path: Path
    thumb_path: Path

    @property
    def size_label(self) -> str:
        return f"{self.width}×{self.height}"


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _app_base_dir() -> Path:
    if getattr(builtins, "__compiled__", False):
        return Path(sys.executable).resolve().parent
    return _project_root()


def custom_outro_root() -> Path:
    path = _app_base_dir() / _CUSTOM_REL
    path.mkdir(parents=True, exist_ok=True)
    return path


def orientation_dir(horizontal: bool) -> Path:
    key: OrientationKey = "landscape" if horizontal else "portrait"
    path = custom_outro_root() / key
    path.mkdir(parents=True, exist_ok=True)
    return path


def _manifest_path() -> Path:
    return custom_outro_root() / _MANIFEST_NAME


def _empty_manifest() -> dict[str, Any]:
    return {
        "landscape": {"selected": "", "items": []},
        "portrait": {"selected": "", "items": []},
    }


def _load_manifest() -> dict[str, Any]:
    _migrate_legacy_files()
    path = _manifest_path()
    if not path.is_file():
        data = _empty_manifest()
        _save_manifest(data)
        return data
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        data = _empty_manifest()
        _save_manifest(data)
        return data
    if not isinstance(raw, dict):
        data = _empty_manifest()
        _save_manifest(data)
        return data
    out = _empty_manifest()
    for key in ("landscape", "portrait"):
        block = raw.get(key) if isinstance(raw.get(key), dict) else {}
        selected = str(block.get("selected") or "").strip()
        items = block.get("items") if isinstance(block.get("items"), list) else []
        cleaned: list[dict] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            item_id = str(it.get("id") or "").strip()
            if not item_id:
                continue
            cleaned.append(
                {
                    "id": item_id,
                    "name": str(it.get("name") or item_id),
                    "width": int(it.get("width") or 0),
                    "height": int(it.get("height") or 0),
                    "file": str(it.get("file") or f"{item_id}.mp4"),
                    "thumb": str(it.get("thumb") or f"{item_id}.jpg"),
                }
            )
        ids = {c["id"] for c in cleaned}
        if selected and selected not in ids:
            selected = ""
        out[key] = {"selected": selected, "items": cleaned}
    return out


def _save_manifest(data: dict[str, Any]) -> None:
    path = _manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _migrate_legacy_files() -> None:
    """把旧版 landscape.mp4 / portrait.mp4 迁入库（仅一次）。"""
    root = custom_outro_root()
    manifest_path = _manifest_path()
    if manifest_path.is_file():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = _empty_manifest()
        except (OSError, ValueError, json.JSONDecodeError):
            data = _empty_manifest()
    else:
        data = _empty_manifest()

    changed = False
    for key, filename in _LEGACY_CUSTOM.items():
        legacy = root / filename
        if not legacy.is_file():
            continue
        horizontal = key == "landscape"
        try:
            w, h = probe_video_size(legacy)
            validate_outro_orientation(legacy, horizontal=horizontal)
        except ValueError:
            continue
        dest_dir = orientation_dir(horizontal)
        item_id = uuid.uuid4().hex[:12]
        video_name = f"{item_id}.mp4"
        thumb_name = f"{item_id}.jpg"
        dest = dest_dir / video_name
        try:
            shutil.move(str(legacy), str(dest))
        except OSError:
            continue
        thumb = dest_dir / thumb_name
        try:
            generate_outro_thumbnail(dest, thumb)
        except ValueError:
            pass
        block = data.setdefault(key, {"selected": "", "items": []})
        if not isinstance(block, dict):
            block = {"selected": "", "items": []}
            data[key] = block
        items = block.setdefault("items", [])
        if not isinstance(items, list):
            items = []
            block["items"] = items
        items.append(
            {
                "id": item_id,
                "name": filename,
                "width": w,
                "height": h,
                "file": video_name,
                "thumb": thumb_name,
            }
        )
        if not str(block.get("selected") or "").strip():
            block["selected"] = item_id
        changed = True
    if changed:
        _save_manifest(data)


def outro_filename(horizontal: bool) -> str:
    return HORIZONTAL_OUTRO if horizontal else VERTICAL_OUTRO


def default_outro_path(horizontal: bool) -> Path | None:
    filename = outro_filename(horizontal)
    bundled = _app_base_dir() / _OUTRO_REL / filename
    if bundled.is_file():
        return bundled
    legacy = _project_root() / filename
    if legacy.is_file():
        return legacy
    return None


def _orientation_key(horizontal: bool) -> OrientationKey:
    return "landscape" if horizontal else "portrait"


def list_outro_items(horizontal: bool) -> list[OutroItem]:
    data = _load_manifest()
    key = _orientation_key(horizontal)
    base = orientation_dir(horizontal)
    items: list[OutroItem] = []
    for raw in data[key]["items"]:
        video = base / raw["file"]
        if not video.is_file():
            continue
        thumb = base / raw["thumb"]
        items.append(
            OutroItem(
                id=raw["id"],
                name=raw["name"],
                width=int(raw["width"] or 0),
                height=int(raw["height"] or 0),
                video_path=video,
                thumb_path=thumb,
            )
        )
    return items


def selected_outro_id(horizontal: bool) -> str:
    data = _load_manifest()
    return str(data[_orientation_key(horizontal)].get("selected") or "")


def set_selected_outro_id(horizontal: bool, item_id: str) -> None:
    """item_id 为空表示使用内置默认。"""
    data = _load_manifest()
    key = _orientation_key(horizontal)
    item_id = str(item_id or "").strip()
    ids = {it["id"] for it in data[key]["items"]}
    if item_id and item_id not in ids:
        raise ValueError("所选片尾不存在")
    data[key]["selected"] = item_id
    _save_manifest(data)


def resolve_outro_path(horizontal: bool) -> str | None:
    """勾选的自定义片尾优先，否则内置默认。"""
    data = _load_manifest()
    key = _orientation_key(horizontal)
    selected = str(data[key].get("selected") or "").strip()
    if selected:
        base = orientation_dir(horizontal)
        for raw in data[key]["items"]:
            if raw["id"] != selected:
                continue
            video = base / raw["file"]
            if video.is_file():
                return str(video)
    default = default_outro_path(horizontal)
    return str(default) if default is not None else None


def probe_video_size(video_path: str | Path) -> tuple[int, int]:
    path = Path(video_path)
    if not path.is_file():
        raise ValueError("文件不存在")
    try:
        ffprobe = resolve_ffprobe()
    except FileNotFoundError as exc:
        raise ValueError(str(exc)) from exc
    try:
        proc = win_run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=s=x:p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception as exc:
        raise ValueError(f"无法读取视频信息：{exc}") from exc
    out = (proc.stdout or "").strip().splitlines()
    line = out[0].strip() if out else ""
    if "x" not in line:
        raise ValueError("视频没有可用的画面流")
    try:
        w_s, h_s = line.split("x", 1)
        w, h = int(w_s), int(h_s)
    except ValueError as exc:
        raise ValueError(f"无法解析视频尺寸：{line}") from exc
    if w <= 0 or h <= 0:
        raise ValueError(f"无效的视频尺寸：{w}x{h}")
    return w, h


def validate_outro_orientation(
    video_path: str | Path, *, horizontal: bool
) -> tuple[int, int]:
    path = Path(video_path)
    suffix = path.suffix.lower()
    if suffix not in _VIDEO_EXTS:
        raise ValueError(
            f"不支持的格式 {suffix or '(无扩展名)'}，请使用 "
            f"{', '.join(sorted(_VIDEO_EXTS))}"
        )
    w, h = probe_video_size(path)
    if horizontal:
        if w < h:
            raise ValueError(
                f"横屏片尾要求画面宽≥高，当前为 {w}×{h}（竖屏），请更换文件"
            )
    else:
        if h < w:
            raise ValueError(
                f"竖屏片尾要求画面高≥宽，当前为 {w}×{h}（横屏），请更换文件"
            )
    return w, h


def generate_outro_thumbnail(video_path: Path, thumb_path: Path) -> Path:
    try:
        ffmpeg = resolve_ffmpeg()
    except FileNotFoundError as exc:
        raise ValueError(str(exc)) from exc
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    # 取靠前一帧，缩放到最长边 _THUMB_SIZE
    scale = (
        f"scale='if(gt(iw,ih),{_THUMB_SIZE},-2)':"
        f"'if(gt(iw,ih),-2,{_THUMB_SIZE})'"
    )
    try:
        win_run(
            [
                ffmpeg,
                "-y",
                "-ss",
                "0.3",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-vf",
                scale,
                "-q:v",
                "3",
                str(thumb_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception as exc:
        raise ValueError(f"生成缩略图失败：{exc}") from exc
    if not thumb_path.is_file():
        raise ValueError("生成缩略图失败：未写出文件")
    return thumb_path


def _safe_display_name(src: Path) -> str:
    name = src.name.strip() or "outro.mp4"
    name = re.sub(r'[<>:"/\\|?*]', "_", name)
    return name[:120]


def add_outro_item(src_path: str | Path, *, horizontal: bool) -> OutroItem:
    """校验、复制进库、生成缩略图，并默认选中新条目。"""
    src = Path(src_path)
    w, h = validate_outro_orientation(src, horizontal=horizontal)
    item_id = uuid.uuid4().hex[:12]
    base = orientation_dir(horizontal)
    video_name = f"{item_id}{src.suffix.lower() or '.mp4'}"
    thumb_name = f"{item_id}.jpg"
    dest = base / video_name
    thumb = base / thumb_name
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    try:
        generate_outro_thumbnail(dest, thumb)
    except ValueError:
        # 缩略图失败不阻断入库
        pass

    data = _load_manifest()
    key = _orientation_key(horizontal)
    entry = {
        "id": item_id,
        "name": _safe_display_name(src),
        "width": w,
        "height": h,
        "file": video_name,
        "thumb": thumb_name,
    }
    data[key]["items"].append(entry)
    data[key]["selected"] = item_id
    _save_manifest(data)
    return OutroItem(
        id=item_id,
        name=entry["name"],
        width=w,
        height=h,
        video_path=dest,
        thumb_path=thumb,
    )


def remove_outro_item(horizontal: bool, item_id: str) -> None:
    data = _load_manifest()
    key = _orientation_key(horizontal)
    item_id = str(item_id or "").strip()
    base = orientation_dir(horizontal)
    kept: list[dict] = []
    for raw in data[key]["items"]:
        if raw["id"] != item_id:
            kept.append(raw)
            continue
        for name in (raw.get("file"), raw.get("thumb")):
            if not name:
                continue
            path = base / str(name)
            if path.is_file():
                path.unlink(missing_ok=True)
    data[key]["items"] = kept
    if data[key].get("selected") == item_id:
        data[key]["selected"] = ""
    _save_manifest(data)


# ---- 兼容旧 API 名称（若外部仍引用）----

def install_custom_outro(src_path: str | Path, *, horizontal: bool) -> Path:
    return add_outro_item(src_path, horizontal=horizontal).video_path


def clear_custom_outro(horizontal: bool) -> bool:
    """清空该方向全部自定义并改回默认。"""
    items = list_outro_items(horizontal)
    for item in items:
        remove_outro_item(horizontal, item.id)
    set_selected_outro_id(horizontal, "")
    return bool(items)


def has_custom_outro(horizontal: bool) -> bool:
    return bool(selected_outro_id(horizontal))


def custom_outro_status_text(horizontal: bool) -> str:
    selected = selected_outro_id(horizontal)
    if not selected:
        return "使用内置默认"
    for item in list_outro_items(horizontal):
        if item.id == selected:
            return f"已选：{item.name}（{item.size_label}）"
    return "使用内置默认"
