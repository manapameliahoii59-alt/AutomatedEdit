import subprocess
import time
from unittest.mock import MagicMock

from app.data.services.render_service import ClipSegment, RenderService


class TestBuildSegments:
    def test_single_file_span(self):
        config = {
            "last_episode": "3.mp4",
            "first_episode_cut_start": 10,
            "full_episodes": [],
            "last_episode_cut_point": 40,
        }
        segments = RenderService.build_segments(config, 40)
        assert segments == [ClipSegment("3.mp4", 10, 40)]

    def test_full_episodes_with_tail_cut(self):
        config = {
            "last_episode": "4.mp4",
            "first_episode_cut_start": 29,
            "full_episodes": ["1.mp4", "2.mp4", "3.mp4"],
            "last_episode_cut_point": 58,
        }
        segments = RenderService.build_segments(config, 58)
        assert segments == [
            ClipSegment("1.mp4", 29, None),
            ClipSegment("2.mp4", 0, None),
            ClipSegment("3.mp4", 0, None),
            ClipSegment("4.mp4", 0, 58),
        ]

    def test_invalid_span_returns_empty(self):
        config = {
            "last_episode": "1.mp4",
            "first_episode_cut_start": 50,
            "full_episodes": [],
            "last_episode_cut_point": 40,
        }
        assert RenderService.build_segments(config, 40) == []


class TestTimeMapping:
    def test_map_time_to_cache(self):
        assert RenderService._map_time_to_cache(29, 1.15) == 29 / 1.15


class TestSceneCache:
    def test_reuses_detect_result(self, monkeypatch):
        calls = {"n": 0}

        def fake_detect(path, detector):
            calls["n"] += 1
            return []

        monkeypatch.setattr("app.data.services.render_service.detect", fake_detect)
        cache: dict[str, list] = {}
        RenderService._optimize_cut("a.mp4", 10.0, cache)
        RenderService._optimize_cut("a.mp4", 12.0, cache)
        assert calls["n"] == 1


class TestRunFfmpeg:
    def test_quiet_ffmpeg_cmd_adds_silence_flags(self):
        cmd = RenderService._quiet_ffmpeg_cmd(["ffmpeg", "-y", "-i", "a.mp4", "out.mp4"])
        assert cmd[:6] == ["ffmpeg", "-hide_banner", "-nostats", "-loglevel", "error", "-y"]

    def test_does_not_block_when_stderr_is_verbose(self, monkeypatch):
        """FFmpeg 大量写 stderr 时不应因 PIPE 满而卡死。"""
        writes = {"n": 0}

        class FakeProc:
            returncode = 0

            def poll(self):
                writes["n"] += 1
                return 0 if writes["n"] >= 3 else None

            def wait(self):
                return 0

            def kill(self):
                pass

        monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: FakeProc())

        ok = RenderService._run_ffmpeg(["ffmpeg", "-version"], "测试")
        assert ok is True

    def test_cancel_kills_running_process(self, monkeypatch):
        proc = MagicMock()
        proc.poll.side_effect = [None, None, 1]
        proc.returncode = -9
        monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: proc)

        cancelled = {"v": False}

        ok = RenderService._run_ffmpeg(
            ["ffmpeg"],
            "测试",
            should_cancel=lambda: (cancelled.__setitem__("v", True) or True),
        )
        assert ok is False
        proc.kill.assert_called_once()
