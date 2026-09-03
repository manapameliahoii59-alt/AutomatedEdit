import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.models import User
from app.services.daily_activity import record_daily_activity
from app.services.daily_quota import (
    assert_can_record,
    build_daily_quota,
    can_clip_drama,
    can_download_drama,
    can_plan_drama,
)


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


def _user(
    plan_limit: int = 0,
    clip_limit: int = 0,
    download_limit: int = 0,
    download_enabled: bool = True,
) -> User:
    return User(
        username="demo",
        password_hash="x",
        daily_plan_limit=plan_limit,
        daily_clip_limit=clip_limit,
        daily_download_limit=download_limit,
        download_enabled=download_enabled,
    )


def test_record_plan_drama(monkeypatch):
    monkeypatch.setattr("app.services.daily_activity._today", lambda: date(2026, 7, 7))
    db = _FakeSession()
    record_daily_activity(db, 1, "plan_drama", "剧A")
    record_daily_activity(db, 1, "plan_drama", "剧B")
    record_daily_activity(db, 1, "plan_drama", "剧A")

    row = db.row
    assert row.plan_count == 2
    assert "剧A" in row.planned_dramas


def test_build_daily_quota_unlimited(monkeypatch):
    monkeypatch.setattr("app.services.daily_activity._today", lambda: date(2026, 7, 7))
    db = _FakeSession()
    quota = build_daily_quota(db, _user(plan_limit=0, clip_limit=0))
    assert quota.can_plan is True
    assert quota.can_clip is True


def test_default_limit_is_thirty(monkeypatch):
    monkeypatch.setattr("app.services.daily_activity._today", lambda: date(2026, 7, 7))
    db = _FakeSession()
    user = _user(plan_limit=30, clip_limit=30)
    quota = build_daily_quota(db, user)
    assert quota.plan_limit == 30
    assert quota.clip_limit == 30


def test_plan_limit_enforced(monkeypatch):
    monkeypatch.setattr("app.services.daily_activity._today", lambda: date(2026, 7, 7))
    db = _FakeSession()
    user = _user(plan_limit=1)
    record_daily_activity(db, 1, "plan_drama", "剧A")

    allowed, message = can_plan_drama(db, user, "剧B")
    assert allowed is False
    assert "策划" in message

    with pytest.raises(HTTPException) as exc:
        assert_can_record(db, user, "plan_drama", "剧B")
    assert exc.value.status_code == 429


def test_repeat_same_drama_allowed(monkeypatch):
    monkeypatch.setattr("app.services.daily_activity._today", lambda: date(2026, 7, 7))
    db = _FakeSession()
    user = _user(plan_limit=1, clip_limit=1)
    record_daily_activity(db, 1, "plan_drama", "剧A")
    record_daily_activity(db, 1, "clip_drama", "剧A")

    assert can_plan_drama(db, user, "剧A")[0] is True
    assert can_clip_drama(db, user, "剧A")[0] is True


def test_download_disabled(monkeypatch):
    monkeypatch.setattr("app.services.daily_activity._today", lambda: date(2026, 7, 7))
    db = _FakeSession()
    user = _user(download_enabled=False)
    allowed, message = can_download_drama(db, user, "剧A")
    assert allowed is False
    assert "未开通" in message


def test_download_limit_enforced(monkeypatch):
    monkeypatch.setattr("app.services.daily_activity._today", lambda: date(2026, 7, 7))
    db = _FakeSession()
    user = _user(download_limit=1)
    record_daily_activity(db, 1, "download_drama", "剧A")

    allowed, message = can_download_drama(db, user, "剧B")
    assert allowed is False
    assert "下载" in message

    with pytest.raises(HTTPException) as exc:
        assert_can_record(db, user, "download_drama", "剧B")
    assert exc.value.status_code == 429

    assert can_download_drama(db, user, "剧A")[0] is True


def test_build_daily_quota_includes_download(monkeypatch):
    monkeypatch.setattr("app.services.daily_activity._today", lambda: date(2026, 7, 7))
    db = _FakeSession()
    user = _user(download_limit=30)
    quota = build_daily_quota(db, user)
    assert quota.download_limit == 30
    assert quota.download_enabled is True
    assert quota.can_download is True
