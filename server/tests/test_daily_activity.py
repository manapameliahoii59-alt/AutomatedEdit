import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.services.daily_activity import record_daily_activity


class _FakeRow:
    def __init__(self):
        self.login_at = None
        self.logout_at = None
        self.downloaded_dramas = "[]"
        self.planned_dramas = "[]"
        self.clipped_dramas = "[]"
        self.plan_count = 0
        self.clip_count = 0


class _FakeSession:
    def __init__(self, row=None):
        self.row = row or _FakeRow()
        self.added = []

    def scalar(self, _stmt):
        return self.row if self.row and getattr(self.row, "_persisted", True) else None

    def add(self, obj):
        self.added.append(obj)
        self.row = obj

    def flush(self):
        if self.row is not None:
            self.row._persisted = True

    @contextmanager
    def begin_nested(self):
        yield


def test_record_login_and_close(monkeypatch):
    monkeypatch.setattr("app.services.daily_activity._today", lambda: date(2026, 7, 6))
    db = _FakeSession(row=None)
    record_daily_activity(db, 1, "app_login")
    row = db.row
    assert row.login_at is not None

    record_daily_activity(db, 1, "app_close")
    assert row.logout_at is not None


def test_record_download_and_clip(monkeypatch):
    monkeypatch.setattr("app.services.daily_activity._today", lambda: date(2026, 7, 6))
    db = _FakeSession()
    record_daily_activity(db, 1, "download_drama", "剧A")
    record_daily_activity(db, 1, "download_drama", "剧B")
    record_daily_activity(db, 1, "clip_drama", "剧A")
    record_daily_activity(db, 1, "clip_drama", "剧C")

    row = db.row
    assert "剧A" in row.downloaded_dramas
    assert "剧B" in row.downloaded_dramas
    assert row.clip_count == 2
