from __future__ import annotations

from PySide6.QtCore import QRectF


def overlay_rect_to_normalized(selection: QRectF, video_rect: QRectF) -> QRectF | None:
    """将 overlay 坐标下的框选矩形映射为视频画面内的归一化矩形 (nx, ny, nw, nh)。"""
    if video_rect.width() < 1 or video_rect.height() < 1:
        return None

    intersected = selection.intersected(video_rect)
    if intersected.width() < 0.01 or intersected.height() < 0.01:
        return None

    nx = (intersected.left() - video_rect.left()) / video_rect.width()
    ny = (intersected.top() - video_rect.top()) / video_rect.height()
    nw = intersected.width() / video_rect.width()
    nh = intersected.height() / video_rect.height()
    return QRectF(nx, ny, nw, nh)


def normalized_to_overlay_rect(normalized: QRectF, video_rect: QRectF) -> QRectF:
    """将归一化矩形还原为 overlay 坐标。"""
    return QRectF(
        video_rect.left() + normalized.x() * video_rect.width(),
        video_rect.top() + normalized.y() * video_rect.height(),
        normalized.width() * video_rect.width(),
        normalized.height() * video_rect.height(),
    )
