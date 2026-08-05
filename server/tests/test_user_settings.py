import sys
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
    assert out.video_download.episode_to == 10
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
    assert result.video_download.episode_to == 10
    assert result.video_download.auto_unzip is False
    assert result.clip_edit.export_name_tag == "阿飞"

    result2 = patch_user_settings(db, 7, {"video_download": {"episode_to": 8}})
    assert result2.video_download.episode_from == 3
    assert result2.video_download.episode_to == 8
    assert result2.video_download.auto_unzip is False


def test_video_download_episode_range_clamped():
    settings = VideoDownloadSettings(episode_from=20, episode_to=3)
    assert settings.episode_from == 10
    assert settings.episode_to == 10
