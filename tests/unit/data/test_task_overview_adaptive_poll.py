from unittest.mock import MagicMock, patch
import pytest

from app.data.services.batch_download_service import (
    BatchDownloadOptions,
    BatchLogger,
    _calculate_adaptive_poll_interval,
    phase2_download_files,
)
from app.data.services.series_list_client import (
    DOWNLOAD_TASK_OVERVIEW_PATH,
    SeriesListClient,
)


class TestSeriesListClientTaskOverview:
    def test_fetch_download_task_overview_path_and_call(self):
        client = SeriesListClient.__new__(SeriesListClient)
        with patch.object(
            client, "_api_fetch", return_value={"code": 0, "data": {"pending_count": 15}}
        ) as mock_fetch:
            data = client.fetch_download_task_overview()
            assert data["code"] == 0
            assert data["data"]["pending_count"] == 15
            mock_fetch.assert_called_once_with(
                DOWNLOAD_TASK_OVERVIEW_PATH,
                {},
                platform=True,
                referer="https://www.changdupingtai.com/sale/download-center",
            )


class TestCalculateAdaptivePollInterval:
    def test_fallback_when_overview_none_or_empty(self):
        interval_0, reason_0 = _calculate_adaptive_poll_interval(None, 0)
        assert 55.0 <= interval_0 <= 65.0
        assert reason_0 == "默认轮询"

        interval_2, reason_2 = _calculate_adaptive_poll_interval({}, 2)
        assert 25.0 <= interval_2 <= 35.0
        assert reason_2 == "默认轮询"

    def test_deep_queue_long_interval(self):
        overview = {
            "pending_count": 25,
            "estimated_wait_seconds": 3600,
            "auto_refresh_seconds": 120,
        }
        interval, reason = _calculate_adaptive_poll_interval(overview, 0)
        assert 110.0 <= interval <= 130.0
        assert "深度排队" in reason
        assert "25部" in reason

    def test_compressing_state_responsive_interval(self):
        overview = {
            "pending_count": 0,
            "compressing_count": 3,
            "encrypting_count": 0,
            "estimated_wait_seconds": 30,
        }
        interval, reason = _calculate_adaptive_poll_interval(overview, 0)
        assert 25.0 <= interval <= 36.0
        assert reason == "压缩打包中"

    def test_small_queue_medium_interval(self):
        overview = {
            "pending_count": 4,
            "compressing_count": 0,
            "encrypting_count": 0,
            "estimated_wait_seconds": 180,
        }
        interval, reason = _calculate_adaptive_poll_interval(overview, 0)
        assert 50.0 <= interval <= 67.0
        assert "排队中" in reason
        assert "4部" in reason


class TestPhase2AdaptiveGatekeeper:
    def test_gatekeeper_skips_task_list_when_queue_unchanged(self, tmp_path):
        client = MagicMock(spec=SeriesListClient)

        # Overview: queue is deep, today_completed_count remains 10
        client.fetch_download_task_overview.return_value = {
            "code": 0,
            "data": {
                "pending_count": 20,
                "compressing_count": 0,
                "processing_count": 20,
                "today_completed_count": 10,
                "estimated_wait_seconds": 2400,
                "auto_refresh_seconds": 120,
            },
        }

        # First round returns task status 1 (transcoding/pending)
        client.fetch_download_tasks_by_ids.return_value = {
            "d_100": {
                "download_id": "d_100",
                "task_status": 1,
                "book_name": "Test Drama",
                "file_path": "",
            }
        }

        opts = BatchDownloadOptions(
            download_dir=str(tmp_path),
            auto_transcribe=False,
        )
        logger = BatchLogger(lambda msg: None, lambda msg: None)

        phase1_results = [
            {
                "key": "d_100",
                "bookName": "Test Drama",
                "downloadId": "d_100",
                "status": "success",
            }
        ]

        poll_counter = {"count": 0}

        def mock_sleep(sec, cancel_check=None):
            poll_counter["count"] += 1
            if poll_counter["count"] >= 3:
                # Cancel after 3 sleep iterations
                raise RuntimeError("任务已取消")

        with patch(
            "app.data.services.batch_download_service._interruptible_sleep",
            side_effect=mock_sleep,
        ):
            with pytest.raises(RuntimeError, match="任务已取消"):
                phase2_download_files(client, phase1_results, opts, set(), logger)

        # fetch_download_task_overview should be polled each round
        assert client.fetch_download_task_overview.call_count >= 3
        # fetch_download_tasks_by_ids should ONLY have been called in round 1 (initial discovery)
        # and bypassed in rounds 2 and 3 because today_completed_count did not increase!
        assert client.fetch_download_tasks_by_ids.call_count == 1

    def test_gatekeeper_triggers_task_list_when_today_completed_increases(self, tmp_path):
        client = MagicMock(spec=SeriesListClient)

        overviews = [
            # Round 1: completed 10
            {
                "code": 0,
                "data": {
                    "pending_count": 5,
                    "processing_count": 5,
                    "today_completed_count": 10,
                },
            },
            # Round 2: completed increased to 11!
            {
                "code": 0,
                "data": {
                    "pending_count": 4,
                    "processing_count": 4,
                    "today_completed_count": 11,
                },
            },
        ]

        def fake_overview():
            if overviews:
                return overviews.pop(0)
            return {
                "code": 0,
                "data": {
                    "pending_count": 4,
                    "processing_count": 4,
                    "today_completed_count": 11,
                },
            }

        client.fetch_download_task_overview.side_effect = fake_overview

        # Mock download task info: finished on second fetch
        task_returns = [
            {
                "d_100": {
                    "download_id": "d_100",
                    "task_status": 1,
                    "book_name": "Test Drama",
                }
            },
            {
                "d_100": {
                    "download_id": "d_100",
                    "task_status": 2,
                    "book_name": "Test Drama",
                    "file_path": "https://example.com/test.zip",
                }
            },
        ]

        def fake_fetch_tasks(*args, **kwargs):
            if task_returns:
                return task_returns.pop(0)
            return {}

        client.fetch_download_tasks_by_ids.side_effect = fake_fetch_tasks

        opts = BatchDownloadOptions(
            download_dir=str(tmp_path),
            auto_transcribe=False,
            auto_unzip_and_delete=False,
        )
        logger = BatchLogger(lambda msg: None, lambda msg: None)

        phase1_results = [
            {
                "key": "d_100",
                "bookName": "Test Drama",
                "downloadId": "d_100",
                "status": "success",
            }
        ]

        zip_file = tmp_path / "test.zip"
        zip_file.write_bytes(b"dummy")

        mock_dl_result = {
            "downloadId": "d_100",
            "bookName": "Test Drama",
            "taskName": "Test Drama",
            "filePath": str(zip_file),
            "downloadUrl": "https://example.com/test.zip",
            "avgSpeedKbps": 1000,
            "elapsedSec": 1,
        }

        with patch(
            "app.data.services.batch_download_service._prepare_download_job",
            side_effect=lambda c, j, o: {
                "downloadId": j["downloadId"],
                "downloadUrl": "https://example.com/test.zip",
                "job": j,
            },
        ), patch(
            "app.data.services.batch_download_service._download_prepared_with_retry",
            return_value=mock_dl_result,
        ), patch(
            "app.data.services.batch_download_service._interruptible_sleep",
            return_value=None,
        ):
            summary = phase2_download_files(client, phase1_results, opts, set(), logger)

        # Both round 1 (initial) and round 2 (triggered by today_completed increment) fetched task details
        assert client.fetch_download_tasks_by_ids.call_count == 2
        assert summary["success"] == 1
