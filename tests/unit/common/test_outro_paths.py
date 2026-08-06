from pathlib import Path
from unittest.mock import patch

import pytest

from app.common import outro_paths as op


def test_validate_outro_orientation_landscape_ok(tmp_path: Path):
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    with patch.object(op, "probe_video_size", return_value=(1280, 720)):
        assert op.validate_outro_orientation(video, horizontal=True) == (1280, 720)


def test_validate_outro_orientation_portrait_reject_landscape(tmp_path: Path):
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    with patch.object(op, "probe_video_size", return_value=(1280, 720)):
        with pytest.raises(ValueError, match="竖屏"):
            op.validate_outro_orientation(video, horizontal=False)


def test_validate_outro_orientation_landscape_reject_portrait(tmp_path: Path):
    video = tmp_path / "a.mp4"
    video.write_bytes(b"x")
    with patch.object(op, "probe_video_size", return_value=(720, 1280)):
        with pytest.raises(ValueError, match="横屏"):
            op.validate_outro_orientation(video, horizontal=True)


def test_validate_outro_rejects_bad_ext(tmp_path: Path):
    video = tmp_path / "a.txt"
    video.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="不支持"):
        op.validate_outro_orientation(video, horizontal=True)


def test_resolve_falls_back_default(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(op, "_app_base_dir", lambda: tmp_path)
    default_dir = tmp_path / "tools" / "outro"
    default_dir.mkdir(parents=True)
    default = default_dir / op.HORIZONTAL_OUTRO
    default.write_bytes(b"default")
    assert op.resolve_outro_path(True) == str(default)


def test_add_select_remove_library(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(op, "_app_base_dir", lambda: tmp_path)
    src = tmp_path / "mine.mp4"
    src.write_bytes(b"payload")

    with (
        patch.object(op, "probe_video_size", return_value=(1080, 1920)),
        patch.object(op, "generate_outro_thumbnail", return_value=tmp_path / "t.jpg"),
    ):
        item = op.add_outro_item(src, horizontal=False)

    assert item.video_path.is_file()
    assert op.selected_outro_id(False) == item.id
    assert op.resolve_outro_path(False) == str(item.video_path)

    op.set_selected_outro_id(False, "")
    default_dir = tmp_path / "tools" / "outro"
    default_dir.mkdir(parents=True, exist_ok=True)
    default = default_dir / op.VERTICAL_OUTRO
    default.write_bytes(b"default")
    assert op.resolve_outro_path(False) == str(default)

    op.remove_outro_item(False, item.id)
    assert item.id not in {i.id for i in op.list_outro_items(False)}


def test_set_selected_unknown_raises(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(op, "_app_base_dir", lambda: tmp_path)
    with pytest.raises(ValueError, match="不存在"):
        op.set_selected_outro_id(True, "missing")
