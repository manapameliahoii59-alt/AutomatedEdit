import time

import pytest

from app.data.services.batch_download_service import (
    DEFAULT_TRANSCODE_TIMEOUT_MIN,
    TRANSCODE_POLL_INTERVALS_SEC,
    _interruptible_sleep,
    _transcode_poll_interval_sec,
    format_download_progress,
)
from app.data.services.series_list_client import SeriesListClient


class TestTranscodePollInterval:
    def test_intervals_follow_60_45_30(self):
        assert _transcode_poll_interval_sec(0) == 60
        assert _transcode_poll_interval_sec(1) == 45
        assert _transcode_poll_interval_sec(2) == 30
        assert _transcode_poll_interval_sec(99) == 30

    def test_default_transcode_timeout_is_15_minutes(self):
        assert DEFAULT_TRANSCODE_TIMEOUT_MIN == 15
        assert TRANSCODE_POLL_INTERVALS_SEC == (60, 45, 30)


class TestInterruptibleSleep:
    def test_raises_when_cancelled(self):
        cancelled = {"v": False}

        def cancel_check():
            cancelled["v"] = True
            return True

        with pytest.raises(RuntimeError, match="任务已取消"):
            _interruptible_sleep(5, cancel_check)

    def test_completes_when_not_cancelled(self):
        start = time.time()
        _interruptible_sleep(0.6, lambda: False, step=0.2)
        assert time.time() - start >= 0.5


class TestDownloadProgressFormat:
    def test_with_total_shows_percent_and_speed(self):
        text = format_download_progress(50 * 1024 * 1024, 100 * 1024 * 1024, 1200)
        assert "50.00 MB/100.00 MB (50%)" in text
        assert "1.2 MB/s" in text

    def test_without_total_omits_percent(self):
        text = format_download_progress(10 * 1024 * 1024, None, 512)
        assert "10.00 MB" in text
        assert "512 KB/s" in text
        assert "%" not in text


class TestFetchDownloadTasksByIds:
    def test_bulk_pages_then_fallback(self, monkeypatch):
        client = SeriesListClient.__new__(SeriesListClient)
        pages = [
            {"data": [{"download_id": "1", "task_status": 1}], "total": 100},
            {"data": [{"download_id": "2", "task_status": 1}], "total": 100},
            {"data": [], "total": 100},
        ]
        calls: list[dict] = []

        def fake_list(opts=None):
            calls.append(dict(opts or {}))
            return pages[len(calls) - 1]

        fallback_ids: list[str] = []

        def fake_find(download_id, options=None):
            fallback_ids.append(download_id)
            if download_id == "3":
                return {"download_id": "3", "task_status": 2}
            return None

        monkeypatch.setattr(client, "fetch_download_task_list", fake_list)
        monkeypatch.setattr(client, "find_download_task", fake_find)

        result = client.fetch_download_tasks_by_ids(
            ["1", "2", "3"],
            start_time="100",
            end_time="200",
            page_size=50,
            max_bulk_pages=3,
        )

        assert set(result.keys()) == {"1", "2", "3"}
        assert len(calls) == 2
        assert calls[0]["page_index"] == "0"
        assert calls[1]["page_index"] == "1"
        assert calls[0]["page_size"] == 50
        assert fallback_ids == ["3"]

    def test_stops_early_when_all_found_on_first_page(self, monkeypatch):
        client = SeriesListClient.__new__(SeriesListClient)
        list_calls = {"n": 0}

        def fake_list(opts=None):
            list_calls["n"] += 1
            return {
                "data": [
                    {"download_id": "1", "task_status": 1},
                    {"download_id": "2", "task_status": 1},
                ],
                "total": 2,
            }

        monkeypatch.setattr(client, "fetch_download_task_list", fake_list)
        monkeypatch.setattr(
            client,
            "find_download_task",
            lambda *_args, **_kwargs: None,
        )

        result = client.fetch_download_tasks_by_ids(["1", "2"], page_size=50, max_bulk_pages=3)
        assert len(result) == 2
        assert list_calls["n"] == 1
