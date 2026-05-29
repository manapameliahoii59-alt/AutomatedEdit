from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaMetaData, QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem

from app.common.my_logger import my_logger as logger
from app.common.video_coords import normalized_to_overlay_rect, overlay_rect_to_normalized
from app.data.models.mask_region import MaskRegion
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsScene,
    QGraphicsView,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


_CLICK_DRAG_THRESHOLD_PX = 6


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


class VideoSurfaceContainer(QWidget):
    """用 QGraphicsVideoItem 在场景内渲染，避免 QVideoWidget 原生窗口跑偏。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(480, 360)
        self.setStyleSheet("background-color: #18181c;")

        self._scene = QGraphicsScene(self)
        self._video_item = QGraphicsVideoItem()
        self._video_item.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self._scene.addItem(self._video_item)
        self._video_item.nativeSizeChanged.connect(self._fit_video_in_view)

        self._view = QGraphicsView(self._scene, self)
        self._view.setFrameShape(QFrame.Shape.NoFrame)
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._view.setStyleSheet("background-color: #18181c; border: none;")
        self._view.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.overlay = SelectionOverlay(self)
        self.overlay.raise_()

    @property
    def video_item(self) -> QGraphicsVideoItem:
        return self._video_item

    def video_display_rect(self) -> QRectF:
        """视频实际画面在 overlay 坐标系中的矩形（不含 letterbox 黑边）。"""
        item_rect = self._video_item.sceneBoundingRect()
        top_left = self._view.mapFromScene(item_rect.topLeft())
        bottom_right = self._view.mapFromScene(item_rect.bottomRight())
        return QRectF(
            QPointF(top_left),
            QPointF(bottom_right),
        ).normalized()

    def native_video_size(self) -> QSizeF:
        return self._video_item.nativeSize()

    def relayout(self):
        rect = self.rect()
        if rect.width() < 1 or rect.height() < 1:
            return
        self._view.setGeometry(rect)
        self.overlay.setGeometry(rect)
        self.overlay.raise_()
        self._scene.setSceneRect(QRectF(0, 0, rect.width(), rect.height()))
        self._fit_video_in_view()

    def _fit_video_in_view(self):
        view_w = self._view.viewport().width()
        view_h = self._view.viewport().height()
        if view_w < 1 or view_h < 1:
            return

        native = self._video_item.nativeSize()
        if not native.isValid() or native.isEmpty():
            self._video_item.setSize(QSizeF(view_w, view_h))
            self._video_item.setPos(0, 0)
            return

        scale = min(view_w / native.width(), view_h / native.height())
        width = native.width() * scale
        height = native.height() * scale
        self._video_item.setSize(QSizeF(width, height))
        self._video_item.setPos((view_w - width) / 2, (view_h - height) / 2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.relayout()

    def showEvent(self, event):
        super().showEvent(event)
        self.relayout()


class VideoPreviewPlayer(QWidget):
    """视频预览 + 播放控制 + 框选叠加层。"""

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
        self._duration_ms = 0
        self._seeking = False
        self._mask_regions: list[MaskRegion] = []
        self._edit_overlay_visible = True
        self._selected_region_index: int = -1
        self._init_player()
        self._init_ui()

    def _init_player(self):
        self._player = QMediaPlayer(self)
        self._audio = QAudioOutput(self)
        self._player.setAudioOutput(self._audio)
        self._player.positionChanged.connect(self._on_player_position)
        self._player.durationChanged.connect(self._on_player_duration)
        self._player.playbackStateChanged.connect(self._on_playback_state)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.errorOccurred.connect(self._on_player_error)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._surface = VideoSurfaceContainer(self)
        layout.addWidget(self._surface, 1)
        self._player.setVideoOutput(self._surface.video_item)
        self._overlay = self._surface.overlay
        self._overlay.selectionFinished.connect(self._on_overlay_selection)
        self._overlay.regionClicked.connect(self.regionClicked.emit)
        self._overlay.emptyClicked.connect(self.emptyClicked.emit)
        self._overlay.set_interactive(True)

    def load(self, file_path: str):
        path = Path(file_path)
        self._player.setSource(QUrl.fromLocalFile(str(path.resolve())))
        self._mask_regions.clear()
        self._overlay.clear_regions()
        self._surface.relayout()
        self.pause()

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
            position_ms = self._player.position()

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
        return self._player.playbackState() != QMediaPlayer.PlaybackState.PlayingState

    def play(self):
        self._player.play()
        self._overlay.set_interactive(False)
        self._overlay.set_show_regions(True)
        self.refresh_regions_at()

    def pause(self):
        self._player.pause()
        self._overlay.set_interactive(True)
        self._overlay.set_show_regions(True)
        self.refresh_regions_at()

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
        self._player.setPosition(max(0, position_ms))
        self._seeking = False

    def duration_ms(self) -> int:
        return self._duration_ms

    def position_ms(self) -> int:
        return self._player.position()

    def frame_duration_ms(self) -> int:
        """单帧时长（毫秒），优先读视频帧率，否则按 30fps 估算。"""
        fps = self._player.metaData().value(QMediaMetaData.Key.VideoFrameRate)
        if fps is not None:
            try:
                rate = float(fps)
                if rate > 0:
                    return max(1, round(1000 / rate))
            except (TypeError, ValueError):
                pass
        return 34

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

    def _on_player_position(self, position_ms: int):
        self.refresh_regions_at(position_ms)
        if not self._seeking:
            self.positionChanged.emit(position_ms)

    def _on_player_duration(self, duration_ms: int):
        self._duration_ms = max(0, duration_ms)
        self.durationChanged.emit(self._duration_ms)

    def _on_playback_state(self, state: QMediaPlayer.PlaybackState):
        paused = state != QMediaPlayer.PlaybackState.PlayingState
        self._overlay.set_interactive(paused)
        self._overlay.set_show_regions(True)
        self.refresh_regions_at()
        self.pausedChanged.emit(paused)

    def _on_media_status(self, status: QMediaPlayer.MediaStatus):
        if status in (
            QMediaPlayer.MediaStatus.LoadedMedia,
            QMediaPlayer.MediaStatus.BufferedMedia,
        ):
            self._surface.relayout()
            self.refresh_regions_at()

    def _on_player_error(self, error: QMediaPlayer.Error, message: str = ""):
        if error == QMediaPlayer.Error.NoError:
            return
        detail = message or str(error)
        logger.warning("视频播放异常 [{}]: {}", Path(self._player.source().toLocalFile()).name, detail)
        self.playbackError.emit(detail)
