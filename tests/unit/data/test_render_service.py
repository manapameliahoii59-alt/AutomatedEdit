import subprocess
import time
from unittest.mock import MagicMock

from app.data.services.render_service import ClipSegment, RenderService, build_atempo_filter


def test_build_atempo_filter_chains_above_2x():
    assert build_atempo_filter(1.15) == "atempo=1.15"
    assert build_atempo_filter(2.0) == "atempo=2"
    assert build_atempo_filter(2.5) == "atempo=2,atempo=1.25"
    assert build_atempo_filter(3.0) == "atempo=2,atempo=1.5"


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


class TestNvencProbe:
    def test_has_nvenc_requires_real_encode(self, monkeypatch, tmp_path):
        calls = {"n": 0}

        def fake_run(cmd, **kwargs):
            calls["n"] += 1
            class R:
                stdout = "h264_nvenc"
                returncode = 1  # 试编失败 = 无可用 GPU
                stderr = "no nvenc device"
            return R()

        monkeypatch.setattr("app.data.services.render_service.win_run", fake_run)
        assert RenderService._has_nvenc("ffmpeg") is False
        assert calls["n"] >= 2  # encoders 列表 + 试编


class TestPreferGpuEnv:
    def test_force_cpu(self, monkeypatch):
        monkeypatch.setenv("AE_FORCE_CPU_ENCODE", "1")
        monkeypatch.delenv("AE_FORCE_GPU_ENCODE", raising=False)
        monkeypatch.setattr(
            RenderService, "_has_nvenc", staticmethod(lambda _ff: True)
        )
        assert RenderService._prefer_gpu("ffmpeg") is False

    def test_force_gpu(self, monkeypatch):
        monkeypatch.delenv("AE_FORCE_CPU_ENCODE", raising=False)
        monkeypatch.setenv("AE_FORCE_GPU_ENCODE", "1")
        monkeypatch.setattr(
            RenderService, "_has_nvenc", staticmethod(lambda _ff: False)
        )
        assert RenderService._prefer_gpu("ffmpeg") is True


class TestEncodePresets:
    def test_normalize_defaults_and_invalid(self):
        assert RenderService.normalize_nvenc_preset(None) == "p5"
        assert RenderService.normalize_nvenc_preset("P7") == "p7"
        assert RenderService.normalize_nvenc_preset("nope") == "p5"
        assert RenderService.normalize_x264_preset("") == "superfast"
        assert RenderService.normalize_x264_preset("ultrafast") == "ultrafast"
        assert RenderService.normalize_x264_preset("slow") == "superfast"

    def test_video_encode_args_use_config(self, monkeypatch):
        monkeypatch.setattr(
            RenderService, "_configured_nvenc_preset", staticmethod(lambda: "p7")
        )
        monkeypatch.setattr(
            RenderService, "_configured_x264_preset", staticmethod(lambda: "ultrafast")
        )
        assert RenderService._video_encode_args(use_gpu=True) == [
            "-c:v", "h264_nvenc", "-preset", "p7", "-cq", "24",
        ]
        assert RenderService._video_encode_args(use_gpu=False) == [
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "22",
        ]


class TestOutputResolution:
    def test_normalize_defaults_and_invalid(self):
        assert RenderService.normalize_render_resolution(None) == "720p"
        assert RenderService.normalize_render_resolution("") == "720p"
        assert RenderService.normalize_render_resolution("1080P") == "1080p"
        assert RenderService.normalize_render_resolution("source") == "source"
        assert RenderService.normalize_render_resolution("4k") == "720p"

    def test_fixed_modes_by_orientation(self, monkeypatch):
        for mode, horizontal, vertical in (
            ("720p", (1280, 720), (720, 1280)),
            ("1080p", (1920, 1080), (1080, 1920)),
        ):
            monkeypatch.setattr(
                RenderService, "configured_resolution", staticmethod(lambda m=mode: m)
            )
            assert (
                RenderService._resolve_target_dims("ffprobe", "a.mp4", "horizontal")
                == horizontal
            )
            assert (
                RenderService._resolve_target_dims("ffprobe", "a.mp4", "vertical")
                == vertical
            )

    def test_source_mode_uses_probed_size_evenized(self, monkeypatch):
        monkeypatch.setattr(
            RenderService, "configured_resolution", staticmethod(lambda: "source")
        )
        # 探测结果已在 _probe_source_size 内偶数化，原样作为目标尺寸
        monkeypatch.setattr(
            RenderService,
            "_probe_source_size",
            staticmethod(lambda ffprobe, path: (1920, 1086)),
        )
        assert (
            RenderService._resolve_target_dims("ffprobe", "a.mp4", "horizontal")
            == (1920, 1086)
        )

    def test_source_mode_probe_failure_falls_back_to_720p(self, monkeypatch):
        monkeypatch.setattr(
            RenderService, "configured_resolution", staticmethod(lambda: "source")
        )
        monkeypatch.setattr(
            RenderService, "_probe_source_size", staticmethod(lambda ffprobe, path: None)
        )
        assert (
            RenderService._resolve_target_dims("ffprobe", "a.mp4", "horizontal")
            == (1280, 720)
        )
        assert (
            RenderService._resolve_target_dims("ffprobe", "a.mp4", "vertical")
            == (720, 1280)
        )

    def test_probe_source_size_parses_and_evenizes(self, monkeypatch):
        class R:
            stdout = "1921x1087"

        monkeypatch.setattr(
            "app.data.services.render_service.win_run", lambda cmd, **kwargs: R()
        )
        assert RenderService._probe_source_size("ffprobe", "a.mp4") == (1920, 1086)

    def test_probe_source_size_error_returns_none(self, monkeypatch):
        def boom(cmd, **kwargs):
            raise RuntimeError("probe failed")

        monkeypatch.setattr("app.data.services.render_service.win_run", boom)
        assert RenderService._probe_source_size("ffprobe", "a.mp4") is None


class TestSceneCache:
    def test_scan_window_around_cut(self):
        start, end = RenderService._scene_scan_window(10.0, radius=3.0)
        assert start == 7.0
        assert end == 13.0
        start0, end0 = RenderService._scene_scan_window(1.0, radius=3.0)
        assert start0 == 0.0
        assert end0 == 4.0

    def test_windowed_detect_and_reuse(self, monkeypatch):
        calls: list[dict] = []

        def fake_detect(path, detector, **kwargs):
            calls.append({"path": path, **kwargs})
            return []

        monkeypatch.setattr("app.data.services.render_service.detect", fake_detect)
        cache: dict = {}
        RenderService._optimize_cut("a.mp4", 10.0, cache)
        RenderService._optimize_cut("a.mp4", 10.0, cache)  # 同窗口复用
        assert len(calls) == 1
        assert calls[0]["start_time"] == 7.0
        assert calls[0]["end_time"] == 13.0

        RenderService._optimize_cut("a.mp4", 30.0, cache)  # 不同切点新窗口
        assert len(calls) == 2
        assert calls[1]["start_time"] == 27.0
        assert calls[1]["end_time"] == 33.0


class _FakeScene:
    def __init__(self, seconds: float):
        self._seconds = seconds

    def get_seconds(self) -> float:
        return self._seconds


class TestOptimizeCutSpeechFloor:
    """台词完整优先：吸附不得把切点提前到台词结束点（AI 切点 - 尾垫）之前。"""

    AI_CUT = 100.3  # = 台词结束 100.0 + 服务端尾垫 0.3

    def _run(self, monkeypatch, scenes, ai_cut=AI_CUT):
        monkeypatch.setattr(
            RenderService,
            "_get_scene_list",
            staticmethod(
                lambda path, cache, *, ai_cut_time: [
                    (_FakeScene(s),) for s in scenes
                ]
            ),
        )
        return RenderService._optimize_cut("a.mp4", ai_cut, {})

    def test_scene_inside_speech_cannot_pull_cut_earlier(self, monkeypatch):
        # 99.2 在台词中间（< 100.0 下限），只能吸附到 101.0
        assert self._run(monkeypatch, [99.2, 101.0]) == 101.0

    def test_scene_at_speech_end_still_snaps(self, monkeypatch):
        # 100.0 恰为台词结束点（= 下限），允许吸附
        assert self._run(monkeypatch, [99.0, 100.0]) == 100.0

    def test_no_allowed_scene_keeps_ai_cut(self, monkeypatch):
        assert self._run(monkeypatch, [99.5, 99.9]) == self.AI_CUT

    def test_nearest_scene_after_cut_wins(self, monkeypatch):
        assert self._run(monkeypatch, [100.1, 101.4]) == 100.1


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
        assert ok == (True, "")

    def test_cancel_kills_running_process(self, monkeypatch):
        proc = MagicMock()
        proc.poll.side_effect = [None, None, 1]
        proc.returncode = -9
        monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: proc)

        cancelled = {"v": False}

        ok, _err = RenderService._run_ffmpeg(
            ["ffmpeg"],
            "测试",
            should_cancel=lambda: (cancelled.__setitem__("v", True) or True),
        )
        assert ok is False
        proc.kill.assert_called_once()
