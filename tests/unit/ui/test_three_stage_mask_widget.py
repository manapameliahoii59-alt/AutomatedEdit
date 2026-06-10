import pytest
from PySide6.QtCore import QRectF

from app.data.models.mask_region import MODE_TRACKING, format_time_ms
from app.ui.components.three_stage_mask_widget import MaskControlPanel, ThreeStageMaskWidget


class TestFormatTimeMs:
    def test_formats_mm_ss(self):
        assert format_time_ms(75_000) == "01:15"
        assert format_time_ms(0) == "00:00"


class TestMaskControlPanel:
    def test_default_values(self, qapp):
        panel = MaskControlPanel()
        assert panel.mask_type() == MaskControlPanel.MASK_GAUSSIAN
        assert panel.intensity() == 50
        assert panel.apply_mode() == MODE_TRACKING

    def test_set_intensity(self, qapp):
        panel = MaskControlPanel()
        panel.set_intensity(80)
        assert panel.intensity() == 80

    def test_track_button_visible(self, qapp):
        panel = MaskControlPanel()
        assert panel.track_btn.isVisible()

    def test_mask_type_emits_signal(self, qapp, qtbot):
        panel = MaskControlPanel()
        with qtbot.waitSignal(panel.maskTypeChanged, timeout=1000):
            panel.type_combo.setCurrentIndex(1)
        assert panel.mask_type() == MaskControlPanel.MASK_MOSAIC


class TestThreeStageMaskWidget:
    def test_init(self, qapp):
        widget = ThreeStageMaskWidget()
        assert widget.intensity() == 50

    def test_set_duration_and_intensity(self, qapp):
        widget = ThreeStageMaskWidget()
        widget.set_duration_ms(120_000)
        widget.set_intensity(30)
        assert widget.intensity() == 30
        assert widget.editor.timeline.duration_ms() == 120_000

    def test_load_episodes_populates_list(self, qapp, tmp_path):
        video = tmp_path / "01.mp4"
        video.write_bytes(b"")
        widget = ThreeStageMaskWidget()
        widget.load_episodes([str(video)])
        assert widget.editor.episode_list.list.count() == 1

    def test_selection_creates_tracking_region(self, qapp, qtbot):
        widget = ThreeStageMaskWidget()
        widget.set_duration_ms(60_000)
        widget.editor._current_path = "dummy.mp4"
        widget.editor.timeline.set_position_ms(12_000)

        with qtbot.waitSignal(widget.selectionFinished, timeout=1000):
            widget.editor.preview.selectionFinished.emit(
                QRectF(0.1, 0.1, 0.2, 0.2)
            )

        segments = widget.editor.timeline.segments()
        assert len(segments) == 1
        assert segments[0].mode == MODE_TRACKING
        assert "智能追踪" in segments[0].display_text()
        assert widget.editor.control_panel.track_btn.isEnabled()

    def test_segment_selection_seeks_to_start(self, qapp, qtbot):
        widget = ThreeStageMaskWidget()
        widget.set_duration_ms(60_000)
        widget.editor._current_path = "dummy.mp4"
        widget.editor.timeline.set_position_ms(12_000)

        with qtbot.waitSignal(widget.selectionFinished, timeout=1000):
            widget.editor.preview.selectionFinished.emit(
                QRectF(0.1, 0.1, 0.2, 0.2)
            )

        widget.editor.timeline.set_position_ms(30_000)
        item = widget.editor.timeline.segment_list.item(0)
        widget.editor.timeline.segment_list.itemClicked.emit(item)
        assert widget.editor.timeline.position_ms() == 12_000

    def test_new_region_does_not_seek_to_previous(self, qapp, qtbot):
        widget = ThreeStageMaskWidget()
        widget.set_duration_ms(60_000)
        widget.editor._current_path = "dummy.mp4"
        widget.editor.timeline.set_position_ms(5_000)

        with qtbot.waitSignal(widget.selectionFinished, timeout=1000):
            widget.editor.preview.selectionFinished.emit(
                QRectF(0.1, 0.1, 0.2, 0.2)
            )

        widget.editor.timeline.set_position_ms(30_000)
        with qtbot.waitSignal(widget.selectionFinished, timeout=1000):
            widget.editor.preview.selectionFinished.emit(
                QRectF(0.2, 0.2, 0.15, 0.15)
            )

        assert widget.editor.timeline.position_ms() == 30_000
        assert len(widget.editor.timeline.segments()) == 2

    def test_track_button_disabled_until_region_selected(self, qapp, qtbot):
        widget = ThreeStageMaskWidget()
        widget.set_duration_ms(60_000)
        widget.editor._current_path = "dummy.mp4"
        widget.editor.timeline.set_position_ms(5_000)

        with qtbot.waitSignal(widget.selectionFinished, timeout=1000):
            widget.editor.preview.selectionFinished.emit(
                QRectF(0.1, 0.1, 0.2, 0.2)
            )
        assert widget.editor.control_panel.track_btn.isEnabled()

        widget.editor._select_region_index(-1)
        assert not widget.editor.control_panel.track_btn.isEnabled()

        with qtbot.waitSignal(widget.selectionFinished, timeout=1000):
            widget.editor.preview.selectionFinished.emit(
                QRectF(0.5, 0.5, 0.1, 0.1)
            )
        assert len(widget.editor.timeline.segments()) == 2
        assert widget.editor.control_panel.track_btn.isEnabled()
        assert widget.editor._pending_tracking_index == 1

    def test_segment_time_change_syncs_seed_for_retrack(self, qapp, qtbot):
        widget = ThreeStageMaskWidget()
        widget.set_duration_ms(60_000)
        widget.editor._current_path = "dummy.mp4"
        widget.editor.timeline.set_position_ms(0)

        with qtbot.waitSignal(widget.selectionFinished, timeout=1000):
            widget.editor.preview.selectionFinished.emit(
                QRectF(0.1, 0.1, 0.2, 0.2)
            )

        region = widget.editor.timeline.segments()[0]
        tracked = region.with_tracking_keyframes(
            [
                (0, 0.0, 0.0, 0.2, 0.2),
                (5000, 0.5, 0.0, 0.2, 0.2),
            ]
        )
        widget.editor._apply_regions([tracked], record_undo=False)
        widget.editor._select_region_index(0)

        widget.editor._on_segment_time_changed(0, 2500, 60_000)
        updated = widget.editor.timeline.segments()[0]
        seed = updated.seed_bbox_for_tracking()
        assert seed is not None
        assert 0.2 < seed[0] < 0.3
        assert widget.editor.control_panel.track_btn.isEnabled()

    def test_preview_region_click_selects_target(self, qapp, qtbot):
        widget = ThreeStageMaskWidget()
        widget.set_duration_ms(60_000)
        widget.editor._current_path = "dummy.mp4"
        widget.editor.timeline.set_position_ms(5_000)

        for rect in (QRectF(0.1, 0.1, 0.2, 0.2), QRectF(0.5, 0.5, 0.1, 0.1)):
            with qtbot.waitSignal(widget.selectionFinished, timeout=1000):
                widget.editor.preview.selectionFinished.emit(rect)

        widget.editor._select_region_index(-1)
        assert not widget.editor.control_panel.track_btn.isEnabled()

        widget.editor.preview.regionClicked.emit(0)
        assert widget.editor._pending_tracking_index == 0
        assert widget.editor.control_panel.track_btn.isEnabled()

    def test_delete_segment_removes_region(self, qapp, qtbot):
        widget = ThreeStageMaskWidget()
        widget.set_duration_ms(60_000)
        widget.editor._current_path = "dummy.mp4"
        widget.editor.timeline.set_position_ms(5_000)

        with qtbot.waitSignal(widget.selectionFinished, timeout=1000):
            widget.editor.preview.selectionFinished.emit(
                QRectF(0.1, 0.1, 0.2, 0.2)
            )

        assert len(widget.editor.timeline.segments()) == 1
        widget.editor.timeline.segment_list.setCurrentRow(0)
        widget.editor.timeline.delete_segment_btn.click()
        assert len(widget.editor.timeline.segments()) == 0
        assert not widget.editor.timeline.delete_segment_btn.isEnabled()

    def test_llm_track_button_enabled_after_segment_drag(self, qapp, qtbot):
        widget = ThreeStageMaskWidget()
        widget.set_duration_ms(60_000)
        widget.editor._current_path = "dummy.mp4"
        widget.editor.timeline.set_position_ms(0)

        with qtbot.waitSignal(widget.selectionFinished, timeout=1000):
            widget.editor.preview.selectionFinished.emit(
                QRectF(0.1, 0.1, 0.2, 0.2)
            )

        timeline = widget.editor.timeline
        assert not timeline.llm_track_btn.isEnabled()
        timeline.segment_list.setCurrentRow(0)
        timeline.segment_end_slider.setValue(45_000)
        assert timeline.llm_track_btn.isEnabled()

    def test_timeline_segment_track_click_seeks(self, qapp, qtbot):
        widget = ThreeStageMaskWidget()
        widget.set_duration_ms(60_000)
        track = widget.editor.timeline.segment_track
        track.set_duration_ms(60_000)
        track.resize(600, 48)

        with qtbot.waitSignal(widget.editor.timeline.positionChanged, timeout=1000):
            track.seekRequested.emit(30_000)
        assert widget.editor.timeline.position_ms() == 30_000

    def test_space_shortcut_toggles_playback(self, qapp, qtbot, monkeypatch):
        widget = ThreeStageMaskWidget()
        toggled: list[bool] = []
        monkeypatch.setattr(
            widget.editor,
            "_toggle_playback",
            lambda: toggled.append(True),
        )
        widget.editor._toggle_playback_if_allowed()
        assert toggled == [True]
