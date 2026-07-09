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
    assert out.updated_at is None


def test_build_settings_out_preserves_unknown_namespace():
    out = build_settings_out(
        {
            "video_download": {"episode_from": 2, "episode_to": 5},
            "clip_edit": {"export_tag": "demo"},
        },
        None,
    )
    assert out.video_download.episode_from == 2
    assert out.model_dump()["clip_edit"] == {"export_tag": "demo"}


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
            "clip_edit": {"foo": "bar"},
        },
    )
    assert isinstance(result, UserSettingsOut)
    assert result.video_download.episode_from == 3
    assert result.video_download.episode_to == 10
    assert result.video_download.auto_unzip is False
    assert result.model_dump()["clip_edit"] == {"foo": "bar"}

    result2 = patch_user_settings(db, 7, {"video_download": {"episode_to": 8}})
    assert result2.video_download.episode_from == 3
    assert result2.video_download.episode_to == 8
    assert result2.video_download.auto_unzip is False


def test_video_download_episode_range_clamped():
    settings = VideoDownloadSettings(episode_from=20, episode_to=3)
    assert settings.episode_from == 10
    assert settings.episode_to == 10
