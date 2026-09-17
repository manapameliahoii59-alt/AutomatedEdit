import sys
import json
from datetime import datetime
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.schemas import UserSettingsOut, VideoDownloadSettings
from app.services.user_settings import build_settings_out, patch_user_settings


class _FakeRow:
    def __init__(self, user_id: int, data: str = "{}"):
        self.user_id = user_id
        self.data = data
        self.updated_at = datetime(2026, 7, 6, 12, 0, 0)
        self._persisted = False


class _FakeSession:
    def __init__(self):
        self.rows: dict[int, _FakeRow] = {}
        self.added: list[_FakeRow] = []

    def add(self, obj):
        self.added.append(obj)
        self.rows[obj.user_id] = obj

    def flush(self):
        for row in self.rows.values():
            row._persisted = True

    def refresh(self, row):
        row.updated_at = datetime(2026, 7, 6, 12, 30, 0)


def test_build_settings_out_defaults():
    out = build_settings_out({}, None)
    assert out.video_download.episode_from == 1
    assert out.video_download.episode_to == 15
    assert out.video_download.auto_unzip is True
    assert out.clip_edit.export_name_tag == ""
    assert out.clip_edit.overlay_title.text == "《{name}》"
    assert out.clip_edit.overlay_title.portrait is not None
    assert out.clip_edit.overlay_title.portrait.y_pct == 94.5
    assert out.clip_edit.overlay_title.landscape is not None
    assert out.clip_edit.overlay_title.landscape.y_pct == 90.0
    assert out.clip_edit.overlay_disclaimer.text == "内容纯属虚构 请勿带入现实"
    assert out.updated_at is None


def test_build_settings_out_preserves_unknown_namespace():
    out = build_settings_out(
        {
            "video_download": {"episode_from": 2, "episode_to": 5},
            "clip_edit": {"export_name_tag": "demo"},
            "custom_ns": {"foo": 1},
        },
        None,
    )
    assert out.video_download.episode_from == 2
    assert out.clip_edit.export_name_tag == "demo"
    assert out.model_dump()["custom_ns"] == {"foo": 1}


def test_patch_user_settings_merge(monkeypatch):
    db = _FakeSession()

    def _fake_get_or_create(_db, user_id):
        row = db.rows.get(user_id)
        if row is None:
            row = _FakeRow(user_id)
            db.rows[user_id] = row
            db.added.append(row)
        return row

    monkeypatch.setattr(
        "app.services.user_settings._get_or_create_row",
        _fake_get_or_create,
    )
    result = patch_user_settings(
        db,
        7,
        {
            "video_download": {
                "episode_from": 3,
                "auto_unzip": False,
            },
            "clip_edit": {"export_name_tag": "阿飞"},
        },
    )
    assert isinstance(result, UserSettingsOut)
    assert result.video_download.episode_from == 3
    assert result.video_download.episode_to == 15
    assert result.video_download.auto_unzip is False
    assert result.clip_edit.export_name_tag == "阿飞"

    result2 = patch_user_settings(db, 7, {"video_download": {"episode_to": 8}})
    assert result2.video_download.episode_from == 3
    assert result2.video_download.episode_to == 8
    assert result2.video_download.auto_unzip is False


def test_patch_clip_edit_overlay_persists_and_export_only_keeps_it(monkeypatch):
    db = _FakeSession()

    def _fake_get_or_create(_db, user_id):
        row = db.rows.get(user_id)
        if row is None:
            row = _FakeRow(user_id)
            db.rows[user_id] = row
            db.added.append(row)
        return row

    monkeypatch.setattr(
        "app.services.user_settings._get_or_create_row",
        _fake_get_or_create,
    )
    patch_user_settings(
        db,
        1,
        {
            "clip_edit": {
                "overlay_title": {
                    "text": "《{name}》",
                    "font": "msyh",
                    "fontsize": 40,
                    "color": "#FFFFFF",
                    "opacity": 0.8,
                    "layout": "vertical",
                    "portrait": {"x_pct": 10.0, "y_pct": 20.0},
                    "landscape": {"x_pct": 3.0, "y_pct": 90.0},
                }
            }
        },
    )
    # 仅更新 export_name_tag 时不应丢掉已保存的叠字
    result = patch_user_settings(
        db, 1, {"clip_edit": {"export_name_tag": "tag"}}
    )
    assert result.clip_edit.export_name_tag == "tag"
    assert result.clip_edit.overlay_title.fontsize == 40
    assert result.clip_edit.overlay_title.layout == "vertical"
    stored = json.loads(db.rows[1].data)
    assert stored["clip_edit"]["overlay_title"]["fontsize"] == 40
    assert "overlay_disclaimer" not in stored["clip_edit"]


def _install_fake_row(monkeypatch, db: _FakeSession) -> None:
    def _fake_get_or_create(_db, user_id):
        row = db.rows.get(user_id)
        if row is None:
            row = _FakeRow(user_id)
            db.rows[user_id] = row
            db.added.append(row)
        return row

    monkeypatch.setattr(
        "app.services.user_settings._get_or_create_row", _fake_get_or_create
    )


def test_build_settings_out_encode_defaults_none():
    out = build_settings_out({}, None)
    assert out.clip_edit.encode_enable_gpu is None
    assert out.clip_edit.encode_nvenc_preset is None
    assert out.clip_edit.encode_amf_preset is None
    assert out.clip_edit.clip_trim_ep1_continued is None
    assert out.clip_edit.clip_auto_retry_failed is None
    # 识别集数上限仅后台可控，未配置时下发默认 15
    assert out.clip_edit.clip_max_transcribe_episodes == 15
    assert out.clip_edit.clip_export_dir is None
    assert out.clip_edit.clip_render_engine is None


def test_patch_clip_edit_encode_settings(monkeypatch):
    db = _FakeSession()
    _install_fake_row(monkeypatch, db)
    result = patch_user_settings(
        db,
        1,
        {
            "clip_edit": {
                "encode_enable_gpu": False,
                "encode_nvenc_preset": "p7",
                "encode_x264_preset": "BOGUS",
                "clip_trim_ep1_continued": True,
                "clip_auto_retry_failed": True,
                "clip_max_transcribe_episodes": 20,
                "clip_export_dir": "D:/out",
                "clip_render_engine": "legacy",
            }
        },
    )
    ce = result.clip_edit
    assert ce.encode_enable_gpu is False
    assert ce.encode_nvenc_preset == "p7"
    assert ce.encode_x264_preset is None  # 非法值被丢弃
    assert ce.clip_trim_ep1_continued is True
    assert ce.clip_auto_retry_failed is True
    assert ce.clip_max_transcribe_episodes == 20
    assert ce.clip_export_dir == "D:/out"
    assert ce.clip_render_engine == "legacy"
    stored = json.loads(db.rows[1].data)
    assert stored["clip_edit"]["encode_nvenc_preset"] == "p7"
    assert stored["clip_edit"]["clip_auto_retry_failed"] is True
    assert stored["clip_edit"]["clip_max_transcribe_episodes"] == 20
    assert stored["clip_edit"]["clip_render_engine"] == "legacy"
    assert "encode_x264_preset" not in stored["clip_edit"]


def test_patch_clip_edit_invalid_render_engine_dropped(monkeypatch):
    db = _FakeSession()
    _install_fake_row(monkeypatch, db)
    result = patch_user_settings(
        db, 1, {"clip_edit": {"clip_render_engine": "super-fast"}}
    )
    assert result.clip_edit.clip_render_engine is None
    stored = json.loads(db.rows[1].data)
    assert "clip_render_engine" not in stored["clip_edit"]
