import pytest
import os
import subprocess
import time
from unittest.mock import MagicMock

from app.data.services.render_service import (
    ClipSegment,
    RenderContext,
    RenderService,
    build_atempo_filter,
)


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
    @pytest.fixture(autouse=True)
    def clean_cache(self):
        RenderService.clear_encoder_cache()
        yield
        RenderService.clear_encoder_cache()

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


class TestMultiGpuDetection:
    @pytest.fixture(autouse=True)
    def clean_cache(self):
        RenderService.clear_encoder_cache()
        yield
        RenderService.clear_encoder_cache()

    def test_encoder_cache_reuses_result_without_probing_again(self, monkeypatch):
        probe_count = {"n": 0}

        def fake_probe(ffmpeg, codec):
            probe_count["n"] += 1
            return codec == "h264_amf"

        monkeypatch.setattr(RenderService, "_is_gpu_enabled", staticmethod(lambda: True))
        monkeypatch.setattr(RenderService, "_has_nvenc", staticmethod(lambda _ff: False))
        monkeypatch.setattr(RenderService, "_probe_codec", fake_probe)

        # 第一次探测：真正探测并缓存
        info1 = RenderService._detect_best_encoder("ffmpeg")
        assert info1.codec_name == "h264_amf"
        first_calls = probe_count["n"]
        assert first_calls > 0

        # 第二次探测（批量渲染下一个剧目）：直接从内存缓存返回，0 次多余探测
        info2 = RenderService._detect_best_encoder("ffmpeg")
        assert info2.codec_name == "h264_amf"
        assert probe_count["n"] == first_calls

    def test_nvenc_preferred(self, monkeypatch):
        monkeypatch.setattr(RenderService, "_is_gpu_enabled", staticmethod(lambda: True))
        monkeypatch.setattr(RenderService, "_has_nvenc", staticmethod(lambda _ff: True))
        monkeypatch.setattr(RenderService, "_probe_codec", staticmethod(lambda _ff, codec: True))
        info = RenderService._detect_best_encoder("ffmpeg")
        assert info.codec_name == "h264_nvenc"
        assert info.is_gpu is True
        assert "NVIDIA" in info.vendor_label

    def test_amf_fallback_when_nvenc_fails(self, monkeypatch):
        monkeypatch.setattr(RenderService, "_is_gpu_enabled", staticmethod(lambda: True))
        monkeypatch.setattr(RenderService, "_has_nvenc", staticmethod(lambda _ff: False))
        monkeypatch.setattr(
            RenderService,
            "_probe_codec",
            staticmethod(lambda _ff, codec: codec == "h264_amf"),
        )
        info = RenderService._detect_best_encoder("ffmpeg")
        assert info.codec_name == "h264_amf"
        assert info.is_gpu is True
        assert "AMD" in info.vendor_label

    def test_qsv_fallback_when_nvenc_amf_fail(self, monkeypatch):
        monkeypatch.setattr(RenderService, "_is_gpu_enabled", staticmethod(lambda: True))
        monkeypatch.setattr(RenderService, "_has_nvenc", staticmethod(lambda _ff: False))
        monkeypatch.setattr(
            RenderService,
            "_probe_codec",
            staticmethod(lambda _ff, codec: codec == "h264_qsv"),
        )
        info = RenderService._detect_best_encoder("ffmpeg")
        assert info.codec_name == "h264_qsv"
        assert info.is_gpu is True
        assert "Intel" in info.vendor_label

    def test_cpu_fallback_when_all_gpu_fail(self, monkeypatch):
        monkeypatch.setattr(RenderService, "_is_gpu_enabled", staticmethod(lambda: True))
        monkeypatch.setattr(RenderService, "_has_nvenc", staticmethod(lambda _ff: False))
        monkeypatch.setattr(RenderService, "_probe_codec", staticmethod(lambda _ff, _c: False))
        info = RenderService._detect_best_encoder("ffmpeg")
        assert info.codec_name == "libx264"
        assert info.is_gpu is False

    def test_gpu_disabled_toggle_forces_cpu(self, monkeypatch):
        monkeypatch.setattr(RenderService, "_is_gpu_enabled", staticmethod(lambda: False))
        monkeypatch.setattr(RenderService, "_has_nvenc", staticmethod(lambda _ff: True))
        info = RenderService._detect_best_encoder("ffmpeg")
        assert info.codec_name == "libx264"
        assert info.is_gpu is False
        assert "已关闭" in info.vendor_label


class TestMultiGpuEncodeArgs:
    def test_amf_args(self):
        args = RenderService._video_encode_args(use_gpu=True, codec="h264_amf")
        assert "-c:v" in args and "h264_amf" in args
        assert "-quality" in args and "speed" in args

    def test_qsv_args(self):
        args = RenderService._video_encode_args(use_gpu=True, codec="h264_qsv")
        assert "-c:v" in args and "h264_qsv" in args
        assert "-preset" in args and "veryfast" in args

    def test_cache_enc_tag_multi(self):
        assert RenderService._cache_enc_tag(True, "h264_amf") == "amfspeed"
        assert RenderService._cache_enc_tag(True, "h264_qsv") == "qsvveryfast"
        assert "nvenc" in RenderService._cache_enc_tag(True, "h264_nvenc")
        assert "x264" in RenderService._cache_enc_tag(False)


class TestCrossVendorPresets:
    def test_normalize_amf_preset(self):
        assert RenderService.normalize_amf_preset(None) == "speed"
        assert RenderService.normalize_amf_preset("Quality") == "quality"
        assert RenderService.normalize_amf_preset("nope") == "speed"

    def test_normalize_qsv_preset(self):
        assert RenderService.normalize_qsv_preset(None) == "veryfast"
        assert RenderService.normalize_qsv_preset("MEDIUM") == "medium"
        assert RenderService.normalize_qsv_preset("nope") == "veryfast"

    def test_amf_qsv_args_use_config(self, monkeypatch):
        monkeypatch.setattr(
            RenderService, "_configured_amf_preset", staticmethod(lambda: "quality")
        )
        monkeypatch.setattr(
            RenderService, "_configured_qsv_preset", staticmethod(lambda: "medium")
        )
        assert RenderService._video_encode_args(use_gpu=True, codec="h264_amf") == [
            "-c:v", "h264_amf", "-quality", "quality",
            "-rc", "cqp", "-qp_i", "24", "-qp_p", "24",
        ]
        assert RenderService._video_encode_args(use_gpu=True, codec="h264_qsv") == [
            "-c:v", "h264_qsv", "-preset", "medium", "-global_quality", "24",
        ]

    def test_cache_enc_tag_reflects_preset(self, monkeypatch):
        monkeypatch.setattr(
            RenderService, "_configured_amf_preset", staticmethod(lambda: "balanced")
        )
        monkeypatch.setattr(
            RenderService, "_configured_qsv_preset", staticmethod(lambda: "fast")
        )
        assert RenderService._cache_enc_tag(True, "h264_amf") == "amfbalanced"
        assert RenderService._cache_enc_tag(True, "h264_qsv") == "qsvfast"

    def test_detect_active_encoder_falls_back_to_cpu_on_error(self, monkeypatch):
        def boom(_ff):
            raise RuntimeError("no ffmpeg")

        monkeypatch.setattr(RenderService, "_detect_best_encoder", staticmethod(boom))
        info = RenderService.detect_active_encoder()
        assert info.codec_name == "libx264"
        assert info.is_gpu is False


class TestPrefixReuse:
    def test_prefix_key_none_without_full_episodes(self):
        assert RenderService._prefix_key({"full_episodes": []}, 1.7) is None
        assert RenderService._prefix_key({}, 1.7) is None

    def test_prefix_key_includes_full_cut_and_speed(self):
        key = RenderService._prefix_key(
            {"full_episodes": ["1.mp4", "2.mp4"], "first_episode_cut_start": 5}, 1.7
        )
        assert key == (("1.mp4", "2.mp4"), 5.0, 1.7)

    def test_reusable_prefix_keys_only_counts_repeats(self):
        def plan(full, cut=0, speed=1.7):
            return {
                "global_speed": speed,
                "files_config": {
                    "full_episodes": full,
                    "first_episode_cut_start": cut,
                },
            }

        keys = RenderService._reusable_prefix_keys(
            [
                plan(["1.mp4"]),
                plan(["1.mp4"]),
                plan(["2.mp4"]),
                plan([]),
                plan(["1.mp4"], cut=5),  # 入点不同 = 不同前缀
                plan(["1.mp4"], speed=1.2),  # 倍速不同 = 不同前缀
            ]
        )
        assert keys == {(("1.mp4",), 0.0, 1.7)}


class TestComposeGraph:
    @staticmethod
    def _ctx():
        return RenderContext(
            project_path="p", target_w=1280, target_h=720, use_gpu=False, enc_v="libx264"
        )

    def test_prefix_graph_without_outro_concats_segments(self):
        segs = [ClipSegment("1.mp4", 0, None), ClipSegment("2.mp4", 0, None)]
        graph = RenderService._build_compose_graph(
            segs, 1.7, self._ctx(), [], [], has_outro=False
        )
        assert "concat=n=2:v=1:a=1[v][a]" in graph
        assert "trim=start=0.000" in graph

    def test_single_prefix_segment_without_outro_avoids_concat(self):
        segs = [ClipSegment("1.mp4", 3.0, None)]
        graph = RenderService._build_compose_graph(
            segs, 2.0, self._ctx(), [], [], has_outro=False
        )
        assert "[v0]null[v];[a0]anull[a]" in graph
        assert "concat" not in graph

    def test_outro_graph_scales_outro_and_appends(self):
        segs = [ClipSegment("1.mp4", 0, None)]
        graph = RenderService._build_compose_graph(
            segs, 1.0, self._ctx(), [], [], has_outro=True
        )
        assert "[1:v]scale=1280:720" in graph
        assert "concat=n=2:v=1:a=1[v][a]" in graph

    def test_overlay_without_outro_passes_through_null(self):
        segs = [ClipSegment("1.mp4", 0, None)]
        graph = RenderService._build_compose_graph(
            segs, 1.0, self._ctx(), ["drawtext=text='x'"], [], has_outro=False
        )
        assert "[vm]null[v]" in graph
        assert "anull[a]" in graph


class TestTryPrefixCompose:
    def _ctx(self, tmp_path):
        ctx = RenderContext(
            project_path="p", target_w=1280, target_h=720, use_gpu=False, enc_v="libx264"
        )
        ctx.prefix_dir = str(tmp_path)
        return ctx

    def test_reuses_cached_prefix_and_stream_copies(self, monkeypatch, tmp_path):
        ctx = self._ctx(tmp_path)
        prefix_file = tmp_path / "prefix_cached.mp4"
        prefix_file.write_bytes(b"x")
        key = (("1.mp4",), 0.0, 1.0)
        ctx.prefix_cache[key] = str(prefix_file)

        calls = {"render": [], "concat": []}

        def fake_render(
            ffmpeg, ffprobe, ctx2, segments, inputs, speed,
            outro, overlay_filters, image_overlays, out, desc, kwargs,
        ):
            calls["render"].append(desc)
            with open(out, "wb") as fh:
                fh.write(b"suffix")
            return True, ""

        def fake_run(cmd, desc, **kwargs):
            calls["concat"].append(desc)
            with open(cmd[-1], "wb") as fh:
                fh.write(b"final")
            return True, ""

        monkeypatch.setattr(
            RenderService, "_render_segments_output", staticmethod(fake_render)
        )
        monkeypatch.setattr(RenderService, "_run_ffmpeg", staticmethod(fake_run))
        monkeypatch.setattr(
            RenderService, "_validate_output", staticmethod(lambda *a, **k: True)
        )

        def fake_probe_duration(ffprobe, path, cache=None):
            name = path.replace("\\", "/").rsplit("/", 1)[-1]
            if name.startswith("ae_suffix_"):
                return 40.0
            if name.startswith("prefix_"):
                return 100.0
            return 140.0

        monkeypatch.setattr(
            RenderService, "_probe_duration", staticmethod(fake_probe_duration)
        )

        ok, dur = RenderService._try_prefix_compose(
            "ffmpeg",
            "ffprobe",
            ctx,
            1.0,
            [ClipSegment("1.mp4", 0, None)],
            ["c1"],
            [ClipSegment("2.mp4", 0, 5)],
            ["c2"],
            "outro.mp4",
            [],
            [],
            str(tmp_path / "out.mp4"),
            key,
            {},
        )
        assert ok is True and dur == 140.0
        # 前缀已缓存：只应渲染尾部+片尾，再做一次流拷贝拼接
        assert calls["render"] == ["尾部+片尾合成"]
        assert calls["concat"] == ["拼接公共前缀+尾部"]

    def test_returns_false_when_final_output_invalid(self, monkeypatch, tmp_path):
        ctx = self._ctx(tmp_path)
        prefix_file = tmp_path / "prefix_cached.mp4"
        prefix_file.write_bytes(b"x")
        ctx.prefix_cache[(("1.mp4",), 0.0, 1.0)] = str(prefix_file)

        def fake_render(*args, **kwargs):
            with open(args[9], "wb") as fh:
                fh.write(b"suffix")
            return True, ""

        def fake_run(cmd, desc, **kwargs):
            with open(cmd[-1], "wb") as fh:
                fh.write(b"final")
            return True, ""

        monkeypatch.setattr(
            RenderService, "_render_segments_output", staticmethod(fake_render)
        )
        monkeypatch.setattr(RenderService, "_run_ffmpeg", staticmethod(fake_run))
        monkeypatch.setattr(
            RenderService, "_validate_output", staticmethod(lambda *a, **k: False)
        )

        ok, dur = RenderService._try_prefix_compose(
            "ffmpeg",
            "ffprobe",
            ctx,
            1.0,
            [ClipSegment("1.mp4", 0, None)],
            ["c1"],
            [ClipSegment("2.mp4", 0, 5)],
            ["c2"],
            "outro.mp4",
            [],
            [],
            str(tmp_path / "out.mp4"),
            (("1.mp4",), 0.0, 1.0),
            {},
        )
        assert ok is False and dur == 0.0

    def test_returns_false_when_concat_truncated(self, monkeypatch, tmp_path):
        ctx = self._ctx(tmp_path)
        prefix_file = tmp_path / "prefix_cached.mp4"
        prefix_file.write_bytes(b"x")
        ctx.prefix_cache[(("1.mp4",), 0.0, 1.0)] = str(prefix_file)

        def fake_render(*args, **kwargs):
            with open(args[9], "wb") as fh:
                fh.write(b"suffix")
            return True, ""

        def fake_run(cmd, desc, **kwargs):
            with open(cmd[-1], "wb") as fh:
                fh.write(b"final")
            return True, ""

        def fake_probe_duration(ffprobe, path, cache=None):
            name = path.replace("\\", "/").rsplit("/", 1)[-1]
            if name.startswith("ae_suffix_"):
                return 40.0
            if name.startswith("prefix_"):
                return 100.0
            return 50.0  # 明显短于前缀+尾部(140s) = 截断

        monkeypatch.setattr(
            RenderService, "_render_segments_output", staticmethod(fake_render)
        )
        monkeypatch.setattr(RenderService, "_run_ffmpeg", staticmethod(fake_run))
        monkeypatch.setattr(
            RenderService, "_validate_output", staticmethod(lambda *a, **k: True)
        )
        monkeypatch.setattr(
            RenderService, "_probe_duration", staticmethod(fake_probe_duration)
        )

        ok, dur = RenderService._try_prefix_compose(
            "ffmpeg",
            "ffprobe",
            ctx,
            1.0,
            [ClipSegment("1.mp4", 0, None)],
            ["c1"],
            [ClipSegment("2.mp4", 0, 5)],
            ["c2"],
            "outro.mp4",
            [],
            [],
            str(tmp_path / "out.mp4"),
            (("1.mp4",), 0.0, 1.0),
            {},
        )
        assert ok is False and dur == 0.0

    def test_returns_false_when_concat_inflated(self, monkeypatch, tmp_path):
        # 时间基错乱会把时长放大（如 140s -> 12000s），也必须回退整段合成
        ctx = self._ctx(tmp_path)
        prefix_file = tmp_path / "prefix_cached.mp4"
        prefix_file.write_bytes(b"x")
        ctx.prefix_cache[(("1.mp4",), 0.0, 1.0)] = str(prefix_file)

        def fake_render(*args, **kwargs):
            with open(args[9], "wb") as fh:
                fh.write(b"suffix")
            return True, ""

        def fake_run(cmd, desc, **kwargs):
            with open(cmd[-1], "wb") as fh:
                fh.write(b"final")
            return True, ""

        def fake_probe_duration(ffprobe, path, cache=None):
            name = path.replace("\\", "/").rsplit("/", 1)[-1]
            if name.startswith("ae_suffix_"):
                return 40.0
            if name.startswith("prefix_"):
                return 100.0
            return 12000.0  # 远大于前缀+尾部(140s) = 时间基错乱

        monkeypatch.setattr(
            RenderService, "_render_segments_output", staticmethod(fake_render)
        )
        monkeypatch.setattr(RenderService, "_run_ffmpeg", staticmethod(fake_run))
        monkeypatch.setattr(
            RenderService, "_validate_output", staticmethod(lambda *a, **k: True)
        )
        monkeypatch.setattr(
            RenderService, "_probe_duration", staticmethod(fake_probe_duration)
        )

        ok, dur = RenderService._try_prefix_compose(
            "ffmpeg",
            "ffprobe",
            ctx,
            1.0,
            [ClipSegment("1.mp4", 0, None)],
            ["c1"],
            [ClipSegment("2.mp4", 0, 5)],
            ["c2"],
            "outro.mp4",
            [],
            [],
            str(tmp_path / "out.mp4"),
            (("1.mp4",), 0.0, 1.0),
            {},
        )
        assert ok is False and dur == 0.0

    def test_concat_cmd_has_timestamp_guards(self, monkeypatch, tmp_path):
        ctx = self._ctx(tmp_path)
        prefix_file = tmp_path / "prefix_cached.mp4"
        prefix_file.write_bytes(b"x")
        key = (("1.mp4",), 0.0, 1.0)
        ctx.prefix_cache[key] = str(prefix_file)
        captured = {}

        def fake_render(*args, **kwargs):
            with open(args[9], "wb") as fh:
                fh.write(b"suffix")
            return True, ""

        def fake_run(cmd, desc, **kwargs):
            captured["cmd"] = cmd
            with open(cmd[-1], "wb") as fh:
                fh.write(b"final")
            return True, ""

        def fake_probe_duration(ffprobe, path, cache=None):
            name = path.replace("\\", "/").rsplit("/", 1)[-1]
            if name.startswith("ae_suffix_"):
                return 40.0
            if name.startswith("prefix_"):
                return 100.0
            return 140.0

        monkeypatch.setattr(
            RenderService, "_render_segments_output", staticmethod(fake_render)
        )
        monkeypatch.setattr(RenderService, "_run_ffmpeg", staticmethod(fake_run))
        monkeypatch.setattr(
            RenderService, "_validate_output", staticmethod(lambda *a, **k: True)
        )
        monkeypatch.setattr(
            RenderService, "_probe_duration", staticmethod(fake_probe_duration)
        )

        ok, _ = RenderService._try_prefix_compose(
            "ffmpeg",
            "ffprobe",
            ctx,
            1.0,
            [ClipSegment("1.mp4", 0, None)],
            ["c1"],
            [ClipSegment("2.mp4", 0, 5)],
            ["c2"],
            "outro.mp4",
            [],
            [],
            str(tmp_path / "out.mp4"),
            key,
            {},
        )
        assert ok is True
        cmd = captured["cmd"]
        assert "-avoid_negative_ts" in cmd and "make_zero" in cmd
        assert "+genpts" in cmd


class TestRenderSegmentsOutput:
    def test_forces_video_track_timescale(self, monkeypatch, tmp_path):
        captured = {}

        def fake_filter_complex(base_cmd, graph, tail_cmd, desc, **kwargs):
            captured["tail"] = tail_cmd
            return True, ""

        monkeypatch.setattr(
            RenderService,
            "_run_ffmpeg_with_filter_complex",
            staticmethod(fake_filter_complex),
        )

        ctx = RenderContext(
            project_path="p", target_w=1280, target_h=720, use_gpu=False, enc_v="libx264"
        )
        ok, err = RenderService._render_segments_output(
            "ffmpeg",
            "ffprobe",
            ctx,
            [ClipSegment("1.mp4", 0, None)],
            ["c1"],
            1.0,
            None,
            [],
            [],
            str(tmp_path / "out.mp4"),
            "测试合成",
            {},
        )
        assert ok is True
        tail = captured["tail"]
        assert "-video_track_timescale" in tail
        assert tail[tail.index("-video_track_timescale") + 1] == "1000000"


class TestOverlayBake:
    @staticmethod
    def _ctx():
        return RenderContext(
            project_path="p", target_w=1280, target_h=720, use_gpu=False, enc_v="libx264"
        )

    def test_empty_filters_returns_none(self, tmp_path):
        assert (
            RenderService._bake_drawtext_overlay_png(
                "ffmpeg", self._ctx(), [], str(tmp_path), {}
            )
            is None
        )

    def test_bakes_once_then_reuses_cache(self, monkeypatch, tmp_path):
        calls = {"n": 0}

        def fake_run(cmd, desc, **kwargs):
            calls["n"] += 1
            with open(cmd[-1], "wb") as fh:
                fh.write(b"PNG")
            return True, ""

        monkeypatch.setattr(RenderService, "_run_ffmpeg", staticmethod(fake_run))
        filters = ["drawtext=text='x':x=1:y=1:fontsize=20:fontcolor=#FFFFFF@1.0"]
        p1 = RenderService._bake_drawtext_overlay_png(
            "ffmpeg", self._ctx(), filters, str(tmp_path), {}
        )
        assert p1 and os.path.isfile(p1)
        p2 = RenderService._bake_drawtext_overlay_png(
            "ffmpeg", self._ctx(), filters, str(tmp_path), {}
        )
        assert p2 == p1
        assert calls["n"] == 1  # 第二次命中缓存，不再渲染

    def test_failure_returns_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(
            RenderService, "_run_ffmpeg", staticmethod(lambda *a, **k: (False, "boom"))
        )
        assert (
            RenderService._bake_drawtext_overlay_png(
                "ffmpeg", self._ctx(), ["drawtext=text='x'"], str(tmp_path), {}
            )
            is None
        )

