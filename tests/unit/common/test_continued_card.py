from app.common.continued_card import (
    covers_tail,
    is_first_episode,
    matches_continued_text,
    trimmed_end,
)
from app.data.services.render_service import ClipSegment, RenderContext, RenderService


class TestContinuedCardHelpers:
    def test_is_first_episode(self):
        assert is_first_episode("1.mp4")
        assert is_first_episode("01.mp4")
        assert is_first_episode(r"C:\x\第1集.mp4")
        assert not is_first_episode("2.mp4")
        assert not is_first_episode("10.mp4")

    def test_matches_continued_text(self):
        assert matches_continued_text("未完待续")
        assert matches_continued_text(" 未 完 待 续 ")
        assert matches_continued_text("预告下集更精彩")
        assert not matches_continued_text("你是谁为什么每天开我的车")

    def test_covers_tail(self):
        assert covers_tail(None, 152.5)
        assert covers_tail(151.0, 152.5)
        assert not covers_tail(140.0, 152.5)
        assert not covers_tail(None, 2.0)

    def test_trimmed_end_pads_extra_tenth(self):
        assert trimmed_end(152.5) == 149.4


class TestTrimFirstEpisodeContinuedCard:
    def test_trims_ep1_when_detected(self, monkeypatch, tmp_path):
        ep1 = tmp_path / "1.mp4"
        ep1.write_bytes(b"x")
        (tmp_path / "2.mp4").write_bytes(b"x")
        ctx = RenderContext(
            project_path=str(tmp_path),
            target_w=720,
            target_h=1280,
            use_gpu=False,
            enc_v="libx264",
        )
        monkeypatch.setattr(
            RenderService, "_probe_duration", staticmethod(lambda *a, **k: 152.5)
        )
        monkeypatch.setattr(
            "app.common.continued_card.detect_continued_card",
            lambda *a, **k: True,
        )
        class _Cfg:
            value = True

        monkeypatch.setattr(
            "app.common.config.cfg.clip_trim_ep1_continued", _Cfg()
        )
        segments = [
            ClipSegment("1.mp4", 29.0, None),
            ClipSegment("2.mp4", 0.0, 40.0),
        ]
        out = RenderService._trim_first_episode_continued_card(
            "ffmpeg", "ffprobe", ctx, segments
        )
        assert out == [
            ClipSegment("1.mp4", 29.0, trimmed_end(152.5)),
            ClipSegment("2.mp4", 0.0, 40.0),
        ]

    def test_skips_when_switch_off(self, monkeypatch, tmp_path):
        class _Cfg:
            value = False

        monkeypatch.setattr(
            "app.common.config.cfg.clip_trim_ep1_continued", _Cfg()
        )
        segments = [ClipSegment("1.mp4", 0.0, None)]
        ctx = RenderContext(
            project_path=str(tmp_path),
            target_w=720,
            target_h=1280,
            use_gpu=False,
            enc_v="libx264",
        )
        out = RenderService._trim_first_episode_continued_card(
            "ffmpeg", "ffprobe", ctx, segments
        )
        assert out == segments

    def test_skips_when_not_covering_tail(self, monkeypatch, tmp_path):
        (tmp_path / "1.mp4").write_bytes(b"x")
        class _Cfg:
            value = True

        monkeypatch.setattr(
            "app.common.config.cfg.clip_trim_ep1_continued", _Cfg()
        )
        monkeypatch.setattr(
            RenderService, "_probe_duration", staticmethod(lambda *a, **k: 152.5)
        )
        called = {"n": 0}

        def fake_detect(*a, **k):
            called["n"] += 1
            return True

        monkeypatch.setattr(
            "app.common.continued_card.detect_continued_card", fake_detect
        )
        segments = [ClipSegment("1.mp4", 10.0, 40.0)]
        ctx = RenderContext(
            project_path=str(tmp_path),
            target_w=720,
            target_h=1280,
            use_gpu=False,
            enc_v="libx264",
        )
        out = RenderService._trim_first_episode_continued_card(
            "ffmpeg", "ffprobe", ctx, segments
        )
        assert out == segments
        assert called["n"] == 0
