import pytest

from app.data.models.mask_region import (
    MODE_CURRENT_FRAME,
    MODE_TIME_RANGE,
    MODE_TRACKING,
    MaskRegion,
    TimeRangeNotReadyError,
    compute_region_time_range,
)


class TestComputeRegionTimeRange:
    def test_current_frame_default(self):
        start, end = compute_region_time_range(5000, 60_000, MODE_CURRENT_FRAME)
        assert start == 5000
        assert end == 5034

    def test_tracking_to_end(self):
        start, end = compute_region_time_range(5000, 60_000, MODE_TRACKING)
        assert start == 5000
        assert end == 60_000

    def test_time_range_requires_marks(self):
        with pytest.raises(TimeRangeNotReadyError):
            compute_region_time_range(1000, 60_000, MODE_TIME_RANGE)

    def test_time_range_with_marks(self):
        start, end = compute_region_time_range(
            1000,
            60_000,
            MODE_TIME_RANGE,
            mark_in_ms=2000,
            mark_out_ms=8000,
        )
        assert start == 2000
        assert end == 8000


class TestMaskRegionDisplay:
    def test_single_frame_label(self):
        region = MaskRegion(0.1, 0.1, 0.2, 0.2, 1000, 1034, label="A", mode=MODE_CURRENT_FRAME)
        assert "单帧" in region.display_text()
        assert "当前帧" in region.display_text()

    def test_tracking_label(self):
        region = MaskRegion(
            0.1,
            0.1,
            0.2,
            0.2,
            1000,
            5000,
            label="A",
            mode=MODE_TRACKING,
            track_keyframes=((1000, 0.1, 0.1, 0.2, 0.2),),
        )
        assert "智能追踪" in region.display_text()
        assert "追踪点" in region.display_text()

    def test_time_range_label(self):
        region = MaskRegion(0.1, 0.1, 0.2, 0.2, 1000, 5000, label="A", mode=MODE_TIME_RANGE)
        assert "关键帧段" in region.display_text()


class TestMaskRegionPlayback:
    def test_bbox_only_active_in_range(self):
        region = MaskRegion(0.1, 0.1, 0.2, 0.2, 1000, 2000, mode=MODE_TIME_RANGE)
        assert region.bbox_at(500) is None
        assert region.bbox_at(1500) == (0.1, 0.1, 0.2, 0.2)
        assert region.bbox_at(2500) is None

    def test_tracking_interpolates_keyframes(self):
        region = MaskRegion(
            0.1,
            0.1,
            0.2,
            0.2,
            0,
            10_000,
            mode=MODE_TRACKING,
            track_keyframes=((0, 0.0, 0.0, 0.2, 0.2), (1000, 0.2, 0.0, 0.2, 0.2)),
        )
        bbox = region.bbox_at(500)
        assert bbox is not None
        assert abs(bbox[0] - 0.1) < 0.01

    def test_tracking_hides_box_after_last_keyframe(self):
        region = MaskRegion(
            0.1,
            0.1,
            0.2,
            0.2,
            0,
            60_000,
            mode=MODE_TRACKING,
            track_keyframes=((0, 0.1, 0.1, 0.2, 0.2), (2000, 0.2, 0.1, 0.2, 0.2)),
        )
        assert region.bbox_at(2000) is not None
        assert region.bbox_at(5000) is None
        assert region.is_active_at(5000) is False

    def test_with_tracking_keyframes_truncates_end(self):
        region = MaskRegion(
            0.1,
            0.1,
            0.2,
            0.2,
            1000,
            90_000,
            mode=MODE_TRACKING,
        )
        updated = region.with_tracking_keyframes(
            [(1000, 0.1, 0.1, 0.2, 0.2), (3500, 0.3, 0.2, 0.2, 0.2)]
        )
        assert updated.end_ms == 3500

    def test_timeline_spans_for_tracking(self):
        region = MaskRegion(
            0.1,
            0.1,
            0.2,
            0.2,
            0,
            3000,
            label="A",
            mode=MODE_TRACKING,
            track_keyframes=((0, 0.1, 0.1, 0.2, 0.2), (1000, 0.2, 0.1, 0.2, 0.2), (2000, 0.3, 0.1, 0.2, 0.2)),
        )
        spans = region.timeline_spans()
        assert len(spans) == 2
        assert spans[0][0] == 0
        assert spans[0][1] == 1000

    def test_time_range_interpolates_keyframes(self):
        region = MaskRegion(
            0.0,
            0.0,
            0.2,
            0.2,
            5000,
            10_000,
            mode=MODE_TIME_RANGE,
            track_keyframes=((5000, 0.0, 0.0, 0.2, 0.2), (10_000, 0.2, 0.0, 0.2, 0.2)),
        )
        bbox = region.bbox_at(7500)
        assert bbox is not None
        assert abs(bbox[0] - 0.1) < 0.01

    def test_upsert_keyframe_merges_nearby(self):
        region = MaskRegion(
            0.1,
            0.1,
            0.2,
            0.2,
            0,
            5000,
            mode=MODE_TIME_RANGE,
            track_keyframes=((1000, 0.1, 0.1, 0.2, 0.2),),
        )
        updated = region.upsert_keyframe(1020, 0.3, 0.3, 0.2, 0.2)
        assert len(updated.track_keyframes) == 1
        assert updated.track_keyframes[0][1] == pytest.approx(0.3)

    def test_time_range_keyframe_count_in_display(self):
        region = MaskRegion(
            0.1,
            0.1,
            0.2,
            0.2,
            1000,
            5000,
            mode=MODE_TIME_RANGE,
            track_keyframes=((1000, 0.1, 0.1, 0.2, 0.2), (5000, 0.2, 0.2, 0.2, 0.2)),
        )
        assert "关键帧" in region.display_text()


class TestMaskRegionTrackingSeed:
    def test_seed_bbox_without_trajectory_uses_top_level(self):
        region = MaskRegion(0.1, 0.2, 0.3, 0.4, 1000, 5000, mode=MODE_TRACKING)
        assert region.seed_bbox_for_tracking() == (0.1, 0.2, 0.3, 0.4)

    def test_seed_bbox_at_start_interpolates_trajectory(self):
        region = MaskRegion(
            0.0,
            0.0,
            0.2,
            0.2,
            0,
            60_000,
            mode=MODE_TRACKING,
            track_keyframes=((0, 0.0, 0.0, 0.2, 0.2), (5000, 0.5, 0.0, 0.2, 0.2)),
        )
        updated = region.with_segment_times(2500, 60_000)
        seed = updated.seed_bbox_for_tracking()
        assert seed is not None
        assert 0.2 < seed[0] < 0.3
        assert updated.nx == pytest.approx(seed[0])

    def test_seed_none_when_in_point_after_tracked_range(self):
        region = MaskRegion(
            0.0,
            0.0,
            0.2,
            0.2,
            0,
            60_000,
            mode=MODE_TRACKING,
            track_keyframes=((0, 0.0, 0.0, 0.2, 0.2), (2000, 0.3, 0.0, 0.2, 0.2)),
        )
        updated = region.with_segment_times(10_000, 60_000)
        assert updated.seed_bbox_for_tracking() is None
        assert updated.track_keyframes == ()

    def test_with_segment_times_trims_keyframes_after_out_point(self):
        region = MaskRegion(
            0.0,
            0.0,
            0.2,
            0.2,
            0,
            60_000,
            mode=MODE_TRACKING,
            track_keyframes=(
                (0, 0.0, 0.0, 0.2, 0.2),
                (3000, 0.3, 0.0, 0.2, 0.2),
                (8000, 0.8, 0.0, 0.2, 0.2),
            ),
        )
        updated = region.with_segment_times(0, 5000)
        assert all(item[0] <= 5000 for item in updated.track_keyframes)
        assert not any(item[0] == 8000 for item in updated.track_keyframes)
