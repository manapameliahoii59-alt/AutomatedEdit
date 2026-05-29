import pytest

cv2 = pytest.importorskip("cv2")
import numpy as np

from app.data.services.object_tracker import (
    DEFAULT_SIMILARITY_THRESHOLD,
    _normalize_box,
    _validate_tracked_box,
)


class TestValidateTrackedBox:
    def test_rejects_tiny_box(self):
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        hist = np.ones((8, 8, 8), dtype=np.float32)
        ok, _ = _validate_tracked_box(
            frame, 0, 0, 1, 1, 100, 100, (0, 0, 10, 10), 10, 10, hist,
            similarity_threshold=DEFAULT_SIMILARITY_THRESHOLD,
            peak_similarity=0.5,
        )
        assert not ok

    def test_accepts_same_color_patch(self):
        frame = np.full((100, 100, 3), 128, dtype=np.uint8)
        from app.data.services.object_tracker import _roi_histogram

        hist = _roi_histogram(frame, 10, 10, 30, 30)
        assert hist is not None
        ok, _peak = _validate_tracked_box(
            frame, 12, 12, 30, 30, 100, 100, (10, 10, 30, 30), 30, 30, hist,
            similarity_threshold=DEFAULT_SIMILARITY_THRESHOLD,
            peak_similarity=0.5,
        )
        assert ok


class TestNormalizeBox:
    def test_clamps_to_unit(self):
        assert _normalize_box(0, 0, 50, 50, 100, 100) == (0.0, 0.0, 0.5, 0.5)
