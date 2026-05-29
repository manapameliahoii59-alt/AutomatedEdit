from PySide6.QtCore import QRectF

from app.common.video_coords import normalized_to_overlay_rect, overlay_rect_to_normalized


class TestVideoCoords:
    def test_overlay_to_normalized_full_video(self):
        video_rect = QRectF(100, 50, 400, 300)
        selection = QRectF(200, 100, 100, 80)
        normalized = overlay_rect_to_normalized(selection, video_rect)
        assert normalized is not None
        assert abs(normalized.x() - 0.25) < 0.001
        assert abs(normalized.y() - 0.166) < 0.01
        assert abs(normalized.width() - 0.25) < 0.001
        assert abs(normalized.height() - 0.266) < 0.01

    def test_overlay_outside_video_returns_none(self):
        video_rect = QRectF(100, 50, 400, 300)
        selection = QRectF(0, 0, 50, 50)
        assert overlay_rect_to_normalized(selection, video_rect) is None

    def test_normalized_round_trip(self):
        video_rect = QRectF(80, 40, 320, 240)
        normalized = QRectF(0.1, 0.2, 0.3, 0.4)
        overlay = normalized_to_overlay_rect(normalized, video_rect)
        restored = overlay_rect_to_normalized(overlay, video_rect)
        assert restored is not None
        assert abs(restored.x() - 0.1) < 0.001
        assert abs(restored.y() - 0.2) < 0.001
        assert abs(restored.width() - 0.3) < 0.001
        assert abs(restored.height() - 0.4) < 0.001
