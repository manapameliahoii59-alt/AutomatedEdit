from __future__ import annotations

from pathlib import Path

import cv2
from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from app.common.my_logger import my_logger as logger
from app.common.video_coords import normalized_to_overlay_rect, overlay_rect_to_normalized
from app.data.models.mask_region import MaskRegion


_CLICK_DRAG_THRESHOLD_PX = 6
_DEFAULT_FPS = 30.0


class SelectionOverlay(QWidget):
    """叠在视频上方的框选层（暂停时可拖拽画框）。"""

    selectionFinished = Signal(QRectF)
    regionClicked = Signal(int)
    emptyClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self._interactive = True
        self._show_regions = True
        self._dragging = False
        self._pending_click_select = False
        self._press_pos = QPointF()
        self._origin = QPointF()
        self._current = QPointF()
        self._selection = QRectF()
        self._regions: list[QRectF] = []
        self._region_labels: list[str] = []
        self._region_source_indices: list[int] = []
        self._selected_source_index: int = -1

    def set_interactive(self, enabled: bool):
        self._interactive = enabled
        if not enabled:
            self._dragging = False
            self._selection = QRectF()
        self.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            not enabled,
        )
        self.update()

    def set_show_regions(self, visible: bool):
        self._show_regions = visible
        self.update()

    def set_regions(self, regions: list[QRectF]):
        self._regions = list(regions)
        self._region_labels = [f"区域{index}" for index, _ in enumerate(regions, start=1)]
        self._region_source_indices = list(range(len(regions)))
        self.update()

    def set_labeled_regions(self, regions: list[tuple[QRectF, str, int]]):
        self._regions = [rect for rect, _label, _idx in regions]
        self._region_labels = [label for _rect, label, _idx in regions]
        self._region_source_indices = [idx for _rect, _label, idx in regions]
        self.update()

    def set_selected_source_index(self, source_index: int):
        self._selected_source_index = source_index
        self.update()

    def add_region(self, region: QRectF):
        self._regions.append(QRectF(region))
        self.update()

    def clear_regions(self):
        self._regions.clear()
        self._region_labels.clear()
        self._region_source_indices.clear()
        self._selected_source_index = -1
        self._selection = QRectF()
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._interactive and not self._regions and self._selection.isNull():
            painter.setPen(QColor(160, 160, 170))
            painter.drawText(
                self.rect().adjusted(12, 12, -12, -12),
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                "暂停状态下，按住鼠标左键拖拽以框选打码区域",
            )
        elif self._interactive and self._regions and self._selection.isNull():
            painter.setPen(QColor(160, 160, 170))
            painter.drawText(
                self.rect().adjusted(12, 12, -12, -12),
                Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter,
                "点击已有框选中目标，再点「开始追踪」；空白处拖拽可画新框",
            )

        if self._show_regions:
            for index, region in enumerate(self._regions):
                label = (
                    self._region_labels[index]
                    if index < len(self._region_labels)
                    else f"区域{index + 1}"
                )
                source_idx = (
                    self._region_source_indices[index]
                    if index < len(self._region_source_indices)
                    else index
                )
                selected = source_idx == self._selected_source_index
                fill = QColor(255, 215, 0, 140) if selected else QColor(0, 120, 215, 100)
                border = QColor(255, 215, 0) if selected else QColor(255, 80, 80)
                self._draw_rect(painter, region, fill, label, border)

        if self._interactive and not self._selection.isNull():
            self._draw_rect(
                painter,
                self._selection,
                QColor(255, 185, 0, 120),
                "当前框选",
                QColor(255, 80, 80),
            )

        painter.end()

    def _hit_test_region(self, pos: QPointF) -> int:
        for index in range(len(self._regions) - 1, -1, -1):
            if self._regions[index].contains(pos):
                return index
        return -1

    def _source_index_at(self, overlay_index: int) -> int:
        if 0 <= overlay_index < len(self._region_source_indices):
            return self._region_source_indices[overlay_index]
        return overlay_index

    def _draw_rect(
        self,
        painter: QPainter,
        rect: QRectF,
        fill: QColor,
        label: str,
        border: QColor | None = None,
    ):
        painter.fillRect(rect, fill)
        painter.setPen(QPen(border or QColor(255, 80, 80), 2, Qt.PenStyle.SolidLine))
        painter.drawRect(rect)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(rect.topLeft() + QPointF(6, 16), label)

    def mousePressEvent(self, event):
        if not self._interactive or event.button() != Qt.MouseButton.LeftButton:
            return
        self._press_pos = event.position()
        hit = self._hit_test_region(self._press_pos)
        if hit >= 0:
            self._pending_click_select = True
            self._dragging = False
            self._selection = QRectF()
            return
        self._pending_click_select = False
        self._dragging = True
        self._origin = self._press_pos
        self._current = self._origin
        self._selection = QRectF(self._origin, self._current).normalized()
        self.update()

    def mouseMoveEvent(self, event):
        if self._pending_click_select and not self._dragging:
            delta = event.position() - self._press_pos
            if delta.manhattanLength() >= _CLICK_DRAG_THRESHOLD_PX:
                self._pending_click_select = False
                self._dragging = True
                self._origin = self._press_pos
                self._current = event.position()
                self._selection = QRectF(self._origin, self._current).normalized()
                self.update()
            return
        if not self._dragging:
            return
        self._current = event.position()
        self._selection = QRectF(self._origin, self._current).normalized()
        self.update()

    def mouseReleaseEvent(self, event):
        if not self._interactive or event.button() != Qt.MouseButton.LeftButton:
            return
        if self._pending_click_select and not self._dragging:
            self._pending_click_select = False
            hit = self._hit_test_region(self._press_pos)
            if hit >= 0:
                self.regionClicked.emit(self._source_index_at(hit))
            return
        if not self._dragging:
            return
        self._dragging = False
        self._pending_click_select = False
        self._current = event.position()
        self._selection = QRectF(self._origin, self._current).normalized()
        if self._selection.width() >= 4 and self._selection.height() >= 4:
            self.selectionFinished.emit(QRectF(self._selection))
        elif self._hit_test_region(self._press_pos) < 0:
            self.emptyClicked.emit()
        self._selection = QRectF()
        self.update()


class VideoFrameDisplay(QWidget):
    """OpenCV 帧绘制层，保持视频宽高比。"""

    nativeSizeChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: #18181c;")
        self._native_size = QSizeF(16, 9)
        self._display_rect = QRectF()
        self._pixmap: QPixmap | None = None

    def set_native_size(self, width: int, height: int):
        if width > 0 and height > 0:
            self._native_size = QSizeF(width, height)
        else:
            self._native_size = QSizeF(16, 9)
        self._update_display_rect()
        self.nativeSizeChanged.emit()
        self.update()

    def set_frame_bgr(self, frame):
        if frame is None:
            self._pixmap = None
            self.update()
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb.shape
        image = QImage(
            rgb.data,
            width,
            height,
            channels * width,
            QImage.Format.Format_RGB888,
        ).copy()
        self._pixmap = QPixmap.fromImage(image)
        self._update_display_rect()
        self.update()

    def video_display_rect(self) -> QRectF:
        return QRectF(self._display_rect)

    def native_video_size(self) -> QSizeF:
        return QSizeF(self._native_size)

    def _update_display_rect(self):
        widget_rect = self.rect()
        if widget_rect.width() < 1 or widget_rect.height() < 1:
            self._display_rect = QRectF()
            return
        native = self._native_size
        if native.width() < 1 or native.height() < 1:
            self._display_rect = QRectF(widget_rect)
            return
        scale = min(widget_rect.width() / native.width(), widget_rect.height() / native.height())
        width = native.width() * scale
        height = native.height() * scale
        x = (widget_rect.width() - width) / 2
        y = (widget_rect.height() - height) / 2
        self._display_rect = QRectF(x, y, width, height)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(24, 24, 28))
        if self._pixmap and not self._pixmap.isNull() and not self._display_rect.isEmpty():
            painter.drawPixmap(self._display_rect.toRect(), self._pixmap)
        painter.end()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_display_rect()
        self.update()


class VideoSurfaceContainer(QWidget):
    """视频帧 + 框选叠加层。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(480, 360)
        self.setStyleSheet("background-color: #18181c;")

        self._frame = VideoFrameDisplay(self)
        self._frame.nativeSizeChanged.connect(self.relayout)

        self.overlay = SelectionOverlay(self)
        self.overlay.raise_()

    def set_frame_bgr(self, frame):
        self._frame.set_frame_bgr(frame)

    def set_native_size(self, width: int, height: int):
        self._frame.set_native_size(width, height)

    def video_display_rect(self) -> QRectF:
        return self._frame.video_display_rect()

    def native_video_size(self) -> QSizeF:
        return self._frame.native_video_size()

    def relayout(self):
        rect = self.rect()
        if rect.width() < 1 or rect.height() < 1:
            return
        self._frame.setGeometry(rect)
        self.overlay.setGeometry(rect)
        self.overlay.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.relayout()

    def showEvent(self, event):
        super().showEvent(event)
        self.relayout()


class VideoPreviewPlayer(QWidget):
    """视频预览 + 播放控制 + 框选叠加层（OpenCV 解码，避免 QMediaPlayer 换源卡死）。"""

    selectionFinished = Signal(QRectF)
    regionClicked = Signal(int)
    emptyClicked = Signal()
    positionChanged = Signal(int)
    durationChanged = Signal(int)
    pausedChanged = Signal(bool)
    playbackError = Signal(str)
    regionsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._cap: cv2.VideoCapture | None = None
        self._video_path = ""
        self._duration_ms = 0
        self._position_ms = 0
        self._fps = _DEFAULT_FPS
        self._paused = True
        self._seeking = False
        self._mask_regions: list[MaskRegion] = []
        self._edit_overlay_visible = True
        self._selected_region_index: int = -1
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._advance_playback)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._surface = VideoSurfaceContainer(self)
        layout.addWidget(self._surface, 1)
        self._overlay = self._surface.overlay
        self._overlay.selectionFinished.connect(self._on_overlay_selection)
        self._overlay.regionClicked.connect(self.regionClicked.emit)
        self._overlay.emptyClicked.connect(self.emptyClicked.emit)
        self._overlay.set_interactive(True)

    def load(self, file_path: str):
        path = Path(file_path)
        if not path.is_file():
            raise OSError(f"视频文件不存在: {path}")

        self.pause()
        self._release_capture()

        cap = cv2.VideoCapture(str(path.resolve()))
        if not cap.isOpened():
            raise OSError(f"无法打开视频: {path.name}")

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        if fps <= 0:
            fps = _DEFAULT_FPS
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

        self._cap = cap
        self._video_path = str(path.resolve())
        self._fps = fps
        self._duration_ms = int(frame_count * 1000 / fps) if frame_count > 0 else 0
        self._mask_regions.clear()
        self._overlay.clear_regions()
        self._surface.set_native_size(width, height)
        self._surface.relayout()

        self._seeking = True
        self._show_frame_at_ms(0)
        self._seeking = False
        self.durationChanged.emit(self._duration_ms)
        self.positionChanged.emit(self._position_ms)
        self._overlay.set_interactive(True)
        self._overlay.set_show_regions(True)

    def video_display_rect(self) -> QRectF:
        return self._surface.video_display_rect()

    def _on_overlay_selection(self, widget_rect: QRectF):
        normalized = overlay_rect_to_normalized(widget_rect, self.video_display_rect())
        if normalized is None:
            return
        self.selectionFinished.emit(normalized)

    def refresh_regions_at(self, position_ms: int | None = None):
        """按当前播放时刻刷新应显示的打码框（仅显示该时刻有效的区域）。"""
        if position_ms is None:
            position_ms = self._position_ms

        if not self._edit_overlay_visible and self.is_paused():
            self._overlay.set_regions([])
            return

        video_rect = self.video_display_rect()
        labeled_regions: list[tuple[QRectF, str, int]] = []
        for index, region in enumerate(self._mask_regions):
            bbox = region.bbox_at(position_ms)
            if bbox is None:
                continue
            nx, ny, nw, nh = bbox
            overlay_rect = normalized_to_overlay_rect(QRectF(nx, ny, nw, nh), video_rect)
            labeled_regions.append((overlay_rect, region.label or "区域", index))

        self._overlay.set_labeled_regions(labeled_regions)
        self._overlay.set_selected_source_index(self._selected_region_index)

    def is_paused(self) -> bool:
        return self._paused

    def play(self):
        if self._cap is None:
            return
        self._paused = False
        self._play_timer.start(max(1, round(1000 / self._fps)))
        self._overlay.set_interactive(False)
        self._overlay.set_show_regions(True)
        self.refresh_regions_at()
        self.pausedChanged.emit(False)

    def pause(self):
        was_playing = not self._paused
        self._paused = True
        self._play_timer.stop()
        self._overlay.set_interactive(True)
        self._overlay.set_show_regions(True)
        self.refresh_regions_at()
        if was_playing:
            self.pausedChanged.emit(True)

    def toggle_playback(self):
        if self.is_paused():
            self.play()
        else:
            self.pause()

    def set_edit_overlay_visible(self, visible: bool):
        """阶段切换时控制是否显示编辑框线（暂停态）。"""
        self._edit_overlay_visible = visible
        self.refresh_regions_at()

    def set_position_ms(self, position_ms: int):
        self._seeking = True
        self._show_frame_at_ms(position_ms)
        self._seeking = False
        self.positionChanged.emit(self._position_ms)

    def duration_ms(self) -> int:
        return self._duration_ms

    def position_ms(self) -> int:
        return self._position_ms

    def frame_duration_ms(self) -> int:
        return max(1, round(1000 / self._fps))

    def set_selected_region_index(self, index: int):
        self._selected_region_index = index
        self._overlay.set_selected_source_index(index)
        self.refresh_regions_at()

    def set_mask_regions(self, regions: list[MaskRegion]):
        self._mask_regions = list(regions)
        if self._selected_region_index >= len(self._mask_regions):
            self._selected_region_index = -1
        self.refresh_regions_at()
        self.regionsChanged.emit()

    def clear_regions(self):
        self._mask_regions.clear()
        self._selected_region_index = -1
        self._overlay.clear_regions()
        self.regionsChanged.emit()

    def _show_frame_at_ms(self, position_ms: int):
        if self._cap is None:
            return
        ms = max(0, position_ms)
        if self._duration_ms > 0:
            ms = min(self._duration_ms, ms)
        self._cap.set(cv2.CAP_PROP_POS_MSEC, ms)
        ok, frame = self._cap.read()
        if ok:
            self._surface.set_frame_bgr(frame)
            self._position_ms = int(self._cap.get(cv2.CAP_PROP_POS_MSEC) or ms)
        else:
            logger.warning("读取视频帧失败 [{} @ {}ms]", Path(self._video_path).name, ms)
            self._position_ms = ms
            self.playbackError.emit(f"无法读取视频帧（{Path(self._video_path).name}）")
        self.refresh_regions_at(self._position_ms)

    def _advance_playback(self):
        frame_ms = self.frame_duration_ms()
        next_ms = self._position_ms + frame_ms
        if self._duration_ms > 0 and next_ms >= self._duration_ms:
            next_ms = self._duration_ms
            self._show_frame_at_ms(next_ms)
            self.positionChanged.emit(self._position_ms)
            self.pause()
            return
        self._show_frame_at_ms(next_ms)
        self.positionChanged.emit(self._position_ms)

    def _release_capture(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def closeEvent(self, event):
        self._release_capture()
        super().closeEvent(event)
