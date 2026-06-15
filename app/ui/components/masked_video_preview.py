from __future__ import annotations

from pathlib import Path

import cv2
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QSlider,
    QSplitter,
    QStyle,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, PrimaryPushButton, SubtitleLabel

from app.common.my_logger import my_logger as logger
from app.data.models.mask_region import MaskRegion
from app.ui.components.video_preview_player import VideoSurfaceContainer


_DEFAULT_FPS = 30.0


class ClickSeekSlider(QSlider):
    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            value = QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(),
                int(event.position().x()), self.width(),
            )
            self.setValue(value)
            event.accept()
        super().mousePressEvent(event)


def _apply_masks_to_frame(frame, regions, position_ms, video_width, video_height):
    for region in regions:
        if not region.is_active_at(position_ms):
            continue
        bbox = region.bbox_at(position_ms)
        if bbox is None:
            continue

        nx, ny, nw, nh = bbox
        x1 = int(nx * video_width)
        y1 = int(ny * video_height)
        x2 = int((nx + nw) * video_width)
        y2 = int((ny + nh) * video_height)

        x1 = max(0, min(video_width, x1))
        x2 = max(0, min(video_width, x2))
        y1 = max(0, min(video_height, y1))
        y2 = max(0, min(video_height, y2))

        if x2 - x1 < 2 or y2 - y1 < 2:
            continue

        roi = frame[y1:y2, x1:x2].copy()
        if roi.size == 0:
            continue

        mask_type = region.mask_type
        intensity = region.intensity

        if mask_type == "gaussian":
            k = int(intensity / 100 * 48) * 2 + 3
            roi = cv2.GaussianBlur(roi, (k, k), 0)
        elif mask_type == "mosaic":
            block = max(2, int(intensity / 100 * 48) + 2)
            sh, sw = roi.shape[:2]
            if sh > 0 and sw > 0:
                small_h = max(1, sh // block)
                small_w = max(1, sw // block)
                small = cv2.resize(roi, (small_w, small_h), interpolation=cv2.INTER_LINEAR)
                roi = cv2.resize(small, (sw, sh), interpolation=cv2.INTER_NEAREST)

        frame[y1:y2, x1:x2] = roi


class MaskedVideoPreview(QWidget):
    """打码预览播放器：多集列表 + 逐帧渲染打码效果，不可编辑框选。"""

    positionChanged = Signal(int)
    durationChanged = Signal(int)
    pausedChanged = Signal(bool)
    playbackError = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cap: cv2.VideoCapture | None = None
        self._video_path = ""
        self._duration_ms = 0
        self._position_ms = 0
        self._fps = _DEFAULT_FPS
        self._paused = True
        self._seeking = False
        self._mask_regions: list[MaskRegion] = []
        self._episodes: list[tuple[str, list[MaskRegion]]] = []
        self._episode_index = -1
        self._play_speed = 1.0
        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._advance_playback)
        self._init_ui()
        self._bind_shortcuts()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)

        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(6)
        left_layout.addWidget(SubtitleLabel("剧集列表", left))

        self.episode_list = QListWidget(left)
        self.episode_list.currentRowChanged.connect(self._on_episode_row_changed)
        left_layout.addWidget(self.episode_list, 1)
        left.setMinimumWidth(130)
        left.setMaximumWidth(200)
        splitter.addWidget(left)

        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self._surface = VideoSurfaceContainer(right)
        self._surface.overlay.set_interactive(False)
        self._surface.overlay.set_show_regions(False)
        right_layout.addWidget(self._surface, 1)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self.play_btn = PrimaryPushButton("播放", right)
        self.play_btn.setFixedWidth(80)
        self.play_btn.clicked.connect(self.toggle_playback)
        controls.addWidget(self.play_btn)

        self.speed_combo = QComboBox(right)
        self.speed_combo.setFixedWidth(72)
        self.speed_combo.addItem("0.5x", 0.5)
        self.speed_combo.addItem("1.0x", 1.0)
        self.speed_combo.addItem("1.5x", 1.5)
        self.speed_combo.addItem("2.0x", 2.0)
        self.speed_combo.addItem("3.0x", 3.0)
        self.speed_combo.addItem("4.0x", 4.0)
        self.speed_combo.setCurrentIndex(1)
        self.speed_combo.currentIndexChanged.connect(self._on_speed_changed)
        controls.addWidget(self.speed_combo)

        self.time_label = BodyLabel("00:00 / 00:00", right)
        controls.addWidget(self.time_label)

        self.seek_slider = ClickSeekSlider(Qt.Orientation.Horizontal, right)
        self.seek_slider.setRange(0, 0)
        self.seek_slider.valueChanged.connect(self._on_seek)
        controls.addWidget(self.seek_slider, 1)

        controls.addStretch(1)
        right_layout.addLayout(controls)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([160, 900])

        layout.addWidget(splitter, 1)

    def clear(self):
        self._release_capture()
        self._video_path = ""
        self._duration_ms = 0
        self._position_ms = 0
        self._mask_regions.clear()
        self._episodes.clear()
        self._episode_index = -1
        self._surface.set_frame_bgr(None)
        self.seek_slider.setRange(0, 0)
        self._update_time_label(0, 0)
        self.play_btn.setText("播放")
        self._surface.overlay.clear_regions()
        self.episode_list.blockSignals(True)
        self.episode_list.clear()
        self.episode_list.blockSignals(False)

    def load_episodes(self, episodes: list[tuple[str, list[MaskRegion]]]):
        """加载所有剧集及其对应的打码区域。"""
        self._episodes = list(episodes)
        self.episode_list.blockSignals(True)
        self.episode_list.clear()
        for idx, (path, _regions) in enumerate(episodes, start=1):
            name = Path(path).name
            self.episode_list.addItem(QListWidgetItem(f"第 {idx} 集\n{name}"))
        self.episode_list.blockSignals(False)

        if episodes:
            self._episode_index = -1
            self.episode_list.setCurrentRow(0)
        else:
            self.clear()

    def select_episode(self, index: int):
        if index < 0 or index >= len(self._episodes):
            return
        if index == self._episode_index:
            return
        self.episode_list.blockSignals(True)
        self.episode_list.setCurrentRow(index)
        self.episode_list.blockSignals(False)
        self._load_episode_at(index)

    def _on_episode_row_changed(self, row: int):
        if row < 0 or row >= len(self._episodes):
            return
        if row == self._episode_index:
            return
        self._load_episode_at(row)

    def _load_episode_at(self, index: int):
        path, regions = self._episodes[index]
        self.load_video(path, regions)
        self._episode_index = index

    def load_video(self, video_path: str, regions: list[MaskRegion] | None = None):
        path = Path(video_path)
        if not path.is_file():
            self.playbackError.emit(f"视频文件不存在: {path}")
            return

        self.pause()
        self._release_capture()

        cap = cv2.VideoCapture(str(path.resolve()))
        if not cap.isOpened():
            self.playbackError.emit(f"无法打开视频: {path.name}")
            return

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
        self._mask_regions = list(regions) if regions else []
        self._surface.set_native_size(width, height)
        self._surface.relayout()

        self.seek_slider.setRange(0, self._duration_ms)

        self._seeking = True
        self._position_ms = 0
        self._show_masked_frame_at_ms(0)
        self._seeking = False
        self.durationChanged.emit(self._duration_ms)
        self.positionChanged.emit(self._position_ms)

    def update_regions(self, regions: list[MaskRegion]):
        self._mask_regions = list(regions)
        if self._episode_index >= 0 and self._episode_index < len(self._episodes):
            path, _ = self._episodes[self._episode_index]
            self._episodes[self._episode_index] = (path, list(regions))
        if not self._paused:
            self.pause()
        self._show_masked_frame_at_ms(self._position_ms)

    def is_paused(self) -> bool:
        return self._paused

    def duration_ms(self) -> int:
        return self._duration_ms

    def position_ms(self) -> int:
        return self._position_ms

    def play(self):
        if self._cap is None:
            return
        self._paused = False
        interval = max(1, int(round(1000 / self._fps) / self._play_speed))
        self._play_timer.start(interval)
        self.play_btn.setText("暂停")
        self.pausedChanged.emit(False)

    def pause(self):
        was_playing = not self._paused
        self._paused = True
        self._play_timer.stop()
        self.play_btn.setText("播放")
        if was_playing:
            self.pausedChanged.emit(True)

    def toggle_playback(self):
        if self.is_paused():
            self.play()
        else:
            self.pause()

    def set_position_ms(self, position_ms: int):
        self._seeking = True
        self._show_masked_frame_at_ms(max(0, min(self._duration_ms, position_ms)))
        self._seeking = False
        self.positionChanged.emit(self._position_ms)

    def _show_masked_frame_at_ms(self, position_ms: int):
        if self._cap is None:
            return
        ms = max(0, position_ms)
        if self._duration_ms > 0:
            ms = min(self._duration_ms, ms)

        self._cap.set(cv2.CAP_PROP_POS_MSEC, ms)
        ok, frame = self._cap.read()
        if not ok:
            logger.warning("蒙版预览读取视频帧失败 [{} @ {}ms]", Path(self._video_path).name, ms)
            self._position_ms = ms
            self.playbackError.emit(f"无法读取视频帧 ({Path(self._video_path).name})")
            self._update_time_label(ms, self._duration_ms)
            return

        actual_ms = int(self._cap.get(cv2.CAP_PROP_POS_MSEC) or ms)
        self._position_ms = actual_ms

        h, w = frame.shape[:2]
        _apply_masks_to_frame(frame, self._mask_regions, actual_ms, w, h)

        self._surface.set_frame_bgr(frame)
        self.seek_slider.blockSignals(True)
        self.seek_slider.setValue(actual_ms)
        self.seek_slider.blockSignals(False)
        self._update_time_label(actual_ms, self._duration_ms)

    def _advance_playback(self):
        frame_ms = max(1, round(1000 / self._fps))
        next_ms = self._position_ms + frame_ms
        if self._duration_ms > 0 and next_ms >= self._duration_ms:
            self._show_masked_frame_at_ms(self._duration_ms)
            self.positionChanged.emit(self._position_ms)
            self.pause()
            return
        self._show_masked_frame_at_ms(next_ms)
        self.positionChanged.emit(self._position_ms)

    def _on_seek(self, value: int):
        if self._seeking:
            return
        self.set_position_ms(value)

    def _on_speed_changed(self, index: int):
        self._play_speed = self.speed_combo.currentData()
        if not self._paused:
            self.pause()
            self.play()

    def _bind_shortcuts(self):
        ctx = Qt.ShortcutContext.WidgetWithChildrenShortcut

        def bind(keys, slot):
            s = QShortcut(QKeySequence(keys), self)
            s.setContext(ctx)
            s.activated.connect(slot)

        bind(Qt.Key.Key_Space, self.toggle_playback)
        bind(Qt.Key.Key_Left, lambda: self._step_ms(-3000))
        bind(Qt.Key.Key_Right, lambda: self._step_ms(3000))
        bind("Shift+Left", lambda: self._step_ms(-10000))
        bind("Shift+Right", lambda: self._step_ms(10000))

    def _step_ms(self, delta: int):
        if self._cap is None:
            return
        new_pos = max(0, min(self._duration_ms, self._position_ms + delta))
        self.set_position_ms(new_pos)

    def _update_time_label(self, position_ms: int, duration_ms: int):
        def fmt(ms: int) -> str:
            s = max(0, ms) // 1000
            m, sec = divmod(s, 60)
            return f"{m:02d}:{sec:02d}"
        self.time_label.setText(f"{fmt(position_ms)} / {fmt(duration_ms)}")

    def _release_capture(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def closeEvent(self, event):
        self._release_capture()
        super().closeEvent(event)
