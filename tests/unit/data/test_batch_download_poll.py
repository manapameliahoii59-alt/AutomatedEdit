import time

import pytest

from app.data.services.batch_download_service import (
    DEFAULT_TRANSCODE_TIMEOUT_MIN,
    PHASE1_CREATE_RETRY_PASSES,
    TRANSCODE_POLL_INTERVALS_SEC,
    BatchDownloadOptions,
    BatchLogger,
    _TranscribePipeline,
    _interruptible_sleep,
    _transcode_poll_interval_sec,
    format_download_progress,
    phase1_create_tasks,
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


class TestPhase1CreateRetry:
    def test_failed_targets_retried_once_at_end(self, monkeypatch):
        assert PHASE1_CREATE_RETRY_PASSES == 1

        client = object()
        calls: list[str] = []

        def fake_find(name):
            return {
                "book_id": f"id-{name}",
                "series_name": name,
                "episode_amount": 10,
            }

        def fake_create(book_id, name, from_ep, to_ep):
            calls.append(name)
            if name == "fail-me" and calls.count("fail-me") == 1:
                return {"code": 1, "message": "busy"}
            return {"code": 0, "task_id": f"task-{name}"}

        monkeypatch.setattr(
            "app.data.services.batch_download_service.SeriesListClient.find_drama_by_name",
            lambda self, name: fake_find(name),
            raising=False,
        )
        # phase1 uses client methods directly
        client_obj = type(
            "C",
            (),
            {
                "find_drama_by_name": staticmethod(fake_find),
                "batch_download_in_range": staticmethod(fake_create),
            },
        )()

        ui_logs: list[str] = []
        logger = BatchLogger(ui_logs.append, lambda _m: None)
        monkeypatch.setattr(
            "app.data.services.batch_download_service._save_pending",
            lambda _jobs: None,
        )
        monkeypatch.setattr(
            "app.data.services.batch_download_service._append_log",
            lambda _row: None,
        )

        targets = [
            {"name": "ok-show", "from": 1, "to": 5, "mode": "name"},
            {"name": "fail-me", "from": 1, "to": 5, "mode": "name"},
        ]
        opts = BatchDownloadOptions(delay_sec=0, skip_done=False)
        jobs = phase1_create_tasks(
            client_obj,
            targets,
            opts,
            {"from": 1, "to": 10},
            set(),
            logger,
        )

        assert len(jobs) == 2
        assert {j["name"] for j in jobs} == {"ok-show", "fail-me"}
        assert calls.count("fail-me") == 2
        assert any("重试创建失败剧目" in line for line in ui_logs)
        assert any("重试创建成功" in line for line in ui_logs)

    def test_still_failed_after_retry_counted(self, monkeypatch):
        def fake_find(name):
            return {
                "book_id": f"id-{name}",
                "series_name": name,
                "episode_amount": 10,
            }

        def fake_create(book_id, name, from_ep, to_ep):
            return {"code": 1, "message": "always fail"}

        client_obj = type(
            "C",
            (),
            {
                "find_drama_by_name": staticmethod(fake_find),
                "batch_download_in_range": staticmethod(fake_create),
            },
        )()
        ui_logs: list[str] = []
        logger = BatchLogger(ui_logs.append, lambda _m: None)
        monkeypatch.setattr(
            "app.data.services.batch_download_service._save_pending",
            lambda _jobs: None,
        )
        monkeypatch.setattr(
            "app.data.services.batch_download_service._append_log",
            lambda _row: None,
        )

        jobs = phase1_create_tasks(
            client_obj,
            [{"name": "bad", "from": 1, "to": 3, "mode": "name"}],
            BatchDownloadOptions(delay_sec=0, skip_done=False),
            {"from": 1, "to": 10},
            set(),
            logger,
        )
        assert jobs == []
        assert any("失败 1 个" in line for line in ui_logs)
        assert any("重试仍失败" in line for line in ui_logs)


class TestTranscribePipelinePoll:
    def test_poll_completed_invokes_callback(self):
        from concurrent.futures import Future

        done: list[str] = []
        logger = BatchLogger(lambda _m: None, lambda _m: None)
        pipeline = _TranscribePipeline(logger, on_transcribe_done=done.append)
        future = Future()
        future.set_result("/tmp/drama")
        pipeline._futures.append(future)

        completed = pipeline.poll_completed()

        assert completed == ["/tmp/drama"]
        assert done == ["/tmp/drama"]
        assert not pipeline.has_pending()
