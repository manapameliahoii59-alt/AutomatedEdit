from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSlider,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    IndeterminateProgressRing,
    PrimaryPushButton,
    PushButton,
    SegmentedWidget,
    SubtitleLabel,
)

from app.data.models.mask_region import (
    MODE_HINTS,
    MODE_TRACKING,
    MaskRegion,
    compute_region_time_range,
    format_time_ms,
)
from app.core.task_manager import task_manager
from app.common.utils import set_window_center, show_dialog
from app.data.services.object_tracker import track_object_in_video
from app.data.services.llm_object_tracker import track_object_with_llm
from app.ui.components.mask_edit_history import MaskEditHistory
from app.ui.components.video_preview_player import VideoPreviewPlayer
from app.ui.components.masked_video_preview import MaskedVideoPreview


def _disable_button_keyboard_activation(button) -> None:
    """防止按钮用空格/回车误触发（例如焦点落到「取消」后空格关闭弹窗）。"""
    button.setAutoDefault(False)
    button.setDefault(False)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)


def _build_anchor_preview_pixmap(
    video_path: str,
    time_ms: int,
    nx: float,
    ny: float,
    nw: float,
    nh: float,
    *,
    max_width: int = 480,
) -> QPixmap | None:
    """读取锚点时刻的视频帧并标出框选区域，供弹窗预览。"""
    import cv2

    capture = cv2.VideoCapture(video_path)
    if not capture.isOpened():
        return None
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        if fps <= 0:
            fps = 30.0
        frame_index = max(0, int(time_ms / 1000 * fps))
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = capture.read()
        if not ok or frame is None:
            return None

        height, width = frame.shape[:2]
        x1 = int(nx * width)
        y1 = int(ny * height)
        x2 = int((nx + nw) * width)
        y2 = int((ny + nh) * height)
        cv2.rectangle(frame, (x1, y1), (x2, y2), (80, 80, 255), 2)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = QImage(
            rgb.data,
            width,
            height,
            3 * width,
            QImage.Format.Format_RGB888,
        ).copy()
        pixmap = QPixmap.fromImage(image)
        if pixmap.width() > max_width:
            pixmap = pixmap.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)
        return pixmap
    finally:
        capture.release()


class LlmAnchorTrackingDialog(QDialog):
    """大模型追踪进行中的锚点说明弹窗（非模态，追踪结束自动关闭）。"""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        region_label: str,
        anchor_time_ms: int,
        preview: QPixmap | None,
    ):
        super().__init__(parent)
        self.setWindowTitle("大模型追踪锚点")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        layout.addWidget(SubtitleLabel("锚点画面", self))
        layout.addWidget(
            BodyLabel(
                f"片段「{region_label}」· 时刻 {format_time_ms(anchor_time_ms)}",
                self,
            )
        )
        layout.addWidget(BodyLabel("以下画面将作为大模型追踪的参考锚点", self))

        preview_label = QLabel(self)
        preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_label.setStyleSheet("background-color: #18181c; border-radius: 4px;")
        if preview is not None and not preview.isNull():
            preview_label.setPixmap(preview)
        else:
            preview_label.setText("无法预览锚点画面")
            preview_label.setMinimumHeight(120)
        layout.addWidget(preview_label)

        status_row = QHBoxLayout()
        spinner = IndeterminateProgressRing(self)
        spinner.setFixedSize(20, 20)
        spinner.setStrokeWidth(3)
        status_row.addWidget(spinner)
        status_row.addWidget(BodyLabel("大模型追踪中，完成后自动关闭…", self))
        status_row.addStretch(1)
        layout.addLayout(status_row)

        self.adjustSize()
        self.setMinimumWidth(max(360, self.width()))
        set_window_center(self)


class EpisodeListWidget(QFrame):
    """左侧剧集列表。"""

    episodeSelected = Signal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(120)
        self.setMaximumWidth(160)
        self._paths: list[str] = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(SubtitleLabel("剧集列表", self))
        self.list = QListWidget(self)
        self.list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self.list, 1)

    def set_episodes(self, video_paths: list[str], *, emit_initial: bool = False):
        self._paths = list(video_paths)
        self.list.blockSignals(True)
        try:
            self.list.clear()
            for index, path in enumerate(self._paths, start=1):
                name = Path(path).name
                self.list.addItem(QListWidgetItem(f"第 {index} 集\n{name}"))
            if self._paths:
                self.list.setCurrentRow(0)
        finally:
            self.list.blockSignals(False)
        if emit_initial and self._paths:
            self.episodeSelected.emit(0, self._paths[0])

    def select_row(self, row: int, *, emit_signal: bool = False):
        self.list.blockSignals(True)
        try:
            self.list.setCurrentRow(row)
        finally:
            self.list.blockSignals(False)
        if emit_signal and 0 <= row < len(self._paths):
            self.episodeSelected.emit(row, self._paths[row])

    def current_path(self) -> str | None:
        row = self.list.currentRow()
        if row < 0 or row >= len(self._paths):
            return None
        return self._paths[row]

    def _on_row_changed(self, row: int):
        if row < 0 or row >= len(self._paths):
            return
        self.episodeSelected.emit(row, self._paths[row])


class MaskControlPanel(QFrame):
    """智能追踪打码设置（当前仅实现追踪模式）。"""

    maskTypeChanged = Signal(str)
    intensityChanged = Signal(int)
    applyModeChanged = Signal(str)

    MASK_GAUSSIAN = "gaussian"
    MASK_MOSAIC = "mosaic"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setMinimumWidth(220)
        self.setMaximumWidth(300)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        layout.addWidget(SubtitleLabel("智能追踪打码", self))

        self.mode_hint = BodyLabel(MODE_HINTS[MODE_TRACKING], self)
        self.mode_hint.setWordWrap(True)
        layout.addWidget(self.mode_hint)

        self.track_btn = PrimaryPushButton("开始追踪", self)
        self.track_btn.setEnabled(False)
        self.track_btn.setToolTip("在画面上选中要打码的框后点击，从当前帧自动追踪至视频结尾")
        _disable_button_keyboard_activation(self.track_btn)
        layout.addWidget(self.track_btn)

        layout.addWidget(BodyLabel("打码类型", self))
        self.type_combo = QComboBox(self)
        self.type_combo.addItem("高斯模糊", self.MASK_GAUSSIAN)
        self.type_combo.addItem("像素马赛克", self.MASK_MOSAIC)
        self.type_combo.currentIndexChanged.connect(self._emit_mask_type)
        layout.addWidget(self.type_combo)

        self.intensity_label = BodyLabel("模糊程度：50", self)
        layout.addWidget(self.intensity_label)
        self.intensity_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.intensity_slider.setRange(1, 100)
        self.intensity_slider.setValue(50)
        self.intensity_slider.valueChanged.connect(self._on_intensity_changed)
        layout.addWidget(self.intensity_slider)
        layout.addStretch(1)

        self._update_intensity_label(50)

    def mask_type(self) -> str:
        return self.type_combo.currentData()

    def intensity(self) -> int:
        return self.intensity_slider.value()

    def set_intensity(self, value: int):
        self.intensity_slider.setValue(max(1, min(100, value)))

    def apply_mode(self) -> str:
        return MODE_TRACKING

    def _emit_mask_type(self, _index: int):
        self.maskTypeChanged.emit(self.mask_type())
        self._update_intensity_label(self.intensity())

    def _on_intensity_changed(self, value: int):
        self._update_intensity_label(value)
        self.intensityChanged.emit(value)

    def _update_intensity_label(self, value: int):
        label = "马赛克大小" if self.mask_type() == self.MASK_MOSAIC else "模糊程度"
        self.intensity_label.setText(f"{label}：{value}")


class ClickSeekSlider(QSlider):
    """进度滑块：点击轨道任意位置即可跳转（不仅限于拖动手柄）。"""

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            value = QStyle.sliderValueFromPosition(
                self.minimum(),
                self.maximum(),
                int(event.position().x()),
                self.width(),
            )
            self.setValue(value)
            event.accept()
        super().mousePressEvent(event)


class MaskSegmentTrack(QWidget):
    """时间轴下方的打码片段可视化轨道。"""

    seekRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._duration_ms = 60_000
        self._segments: list[MaskRegion] = []
        self._mark_in_ms: int | None = None
        self._mark_out_ms: int | None = None
        self._selected_index: int = -1

    def set_duration_ms(self, duration_ms: int):
        self._duration_ms = max(1, duration_ms)
        self.update()

    def set_segments(self, segments: list[MaskRegion]):
        self._segments = list(segments)
        self.update()

    def set_mark_points(self, mark_in_ms: int | None, mark_out_ms: int | None):
        self._mark_in_ms = mark_in_ms
        self._mark_out_ms = mark_out_ms
        self.update()

    def set_selected_index(self, index: int):
        self._selected_index = index
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(32, 32, 36))

        track = self.rect().adjusted(8, 20, -8, -8)
        painter.setPen(QPen(QColor(70, 70, 78), 1))
        painter.drawRect(track)

        if (
            self._mark_in_ms is not None
            and self._mark_out_ms is not None
            and self._mark_out_ms > self._mark_in_ms
        ):
            in_ratio = self._mark_in_ms / self._duration_ms
            out_ratio = min(1.0, self._mark_out_ms / self._duration_ms)
            sel_left = track.left() + int(track.width() * in_ratio)
            sel_width = max(2, int(track.width() * (out_ratio - in_ratio)))
            painter.fillRect(
                QRectF(sel_left, track.top(), sel_width, track.height()),
                QColor(255, 255, 255, 25),
            )

        for index, segment in enumerate(self._segments):
            spans = segment.timeline_spans()
            for span_index, (start_ms, end_ms, _label) in enumerate(spans):
                start_ratio = start_ms / self._duration_ms
                end_ratio = min(1.0, end_ms / self._duration_ms)
                bar_left = track.left() + int(track.width() * start_ratio)
                bar_width = max(4, int(track.width() * (end_ratio - start_ratio)))
                bar_rect = QRectF(bar_left, track.top() + 2, bar_width, track.height() - 4)
                if index == self._selected_index:
                    color = QColor(255, 215, 0, 200)
                elif index % 2 == 0:
                    color = QColor(0, 120, 215, 180)
                else:
                    color = QColor(255, 140, 0, 180)
                if len(spans) > 1:
                    color.setAlpha(max(120, color.alpha() - span_index * 15))
                painter.fillRect(bar_rect, color)

        for mark_ms, color in (
            (self._mark_in_ms, QColor(80, 220, 120)),
            (self._mark_out_ms, QColor(255, 100, 100)),
        ):
            if mark_ms is None:
                continue
            ratio = min(1.0, mark_ms / self._duration_ms)
            x = track.left() + int(track.width() * ratio)
            painter.setPen(QPen(color, 2))
            painter.drawLine(x, track.top() - 2, x, track.bottom() + 2)

        painter.setPen(QColor(180, 180, 190))
        painter.drawText(8, 14, "打码片段时间表（绿=入点  红=出点  多段=关键帧/追踪）")
        painter.end()

    def _track_rect(self) -> QRectF:
        return QRectF(self.rect().adjusted(8, 20, -8, -8))

    def _ms_at(self, x: float) -> int:
        track = self._track_rect()
        if track.width() <= 0:
            return 0
        ratio = max(0.0, min(1.0, (x - track.left()) / track.width()))
        return int(ratio * self._duration_ms)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            track = self._track_rect()
            if track.contains(event.position()):
                self.seekRequested.emit(self._ms_at(event.position().x()))
                event.accept()
                return
        super().mousePressEvent(event)


class MaskTimelineWidget(QWidget):
    """底部时间轴：进度滑块 + 入出点 + 片段轨道 + 片段列表。"""

    positionChanged = Signal(int)
    segmentSelected = Signal(int)
    segmentActivated = Signal(int)
    segmentTimeChanged = Signal(int, int, int)
    segmentDeleteRequested = Signal(int)
    llmTrackRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._duration_ms = 60_000
        self._segments: list[MaskRegion] = []
        self._mark_in_ms: int | None = None
        self._mark_out_ms: int | None = None
        self._selected_index: int = -1
        self._syncing_segment_sliders = False
        self._segment_times_adjusted = False
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        row = QHBoxLayout()
        self.time_label = BodyLabel("00:00 / 01:00", self)
        row.addWidget(self.time_label)
        row.addStretch(1)
        layout.addLayout(row)

        self._mark_row = QWidget(self)
        mark_layout = QHBoxLayout(self._mark_row)
        mark_layout.setContentsMargins(0, 0, 0, 0)
        mark_layout.addWidget(BodyLabel("关键帧段：", self._mark_row))
        self.mark_in_btn = PushButton("设为入点 [I]", self._mark_row)
        self.mark_out_btn = PushButton("设为出点 [O]", self._mark_row)
        self.clear_marks_btn = PushButton("清除入出点", self._mark_row)
        self.mark_in_btn.clicked.connect(self._mark_in)
        self.mark_out_btn.clicked.connect(self._mark_out)
        self.clear_marks_btn.clicked.connect(self._clear_marks)
        mark_layout.addWidget(self.mark_in_btn)
        mark_layout.addWidget(self.mark_out_btn)
        mark_layout.addWidget(self.clear_marks_btn)
        mark_layout.addStretch(1)
        layout.addWidget(self._mark_row)

        self.range_label = BodyLabel(
            "请先设置入点和出点；在入点处框选，再在出点或其它时刻框选以添加关键帧",
            self,
        )
        layout.addWidget(self.range_label)

        self.progress_slider = ClickSeekSlider(Qt.Orientation.Horizontal, self)
        self.progress_slider.setRange(0, self._duration_ms)
        self.progress_slider.valueChanged.connect(self._on_position_changed)
        layout.addWidget(self.progress_slider)

        self.segment_track = MaskSegmentTrack(self)
        self.segment_track.seekRequested.connect(self.set_position_ms)
        layout.addWidget(self.segment_track)

        segment_edit = QHBoxLayout()
        self.segment_edit_label = BodyLabel("片段时长：选中列表中的片段后可调整", self)
        segment_edit.addWidget(self.segment_edit_label)
        segment_edit.addWidget(BodyLabel("入", self))
        self.segment_start_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.segment_start_slider.setEnabled(False)
        self.segment_start_slider.valueChanged.connect(self._on_segment_start_changed)
        segment_edit.addWidget(self.segment_start_slider, 1)
        segment_edit.addWidget(BodyLabel("出", self))
        self.segment_end_slider = QSlider(Qt.Orientation.Horizontal, self)
        self.segment_end_slider.setEnabled(False)
        self.segment_end_slider.valueChanged.connect(self._on_segment_end_changed)
        segment_edit.addWidget(self.segment_end_slider, 1)
        layout.addLayout(segment_edit)

        segment_row = QHBoxLayout()
        self.segment_list = QListWidget(self)
        self.segment_list.setMaximumHeight(96)
        self.segment_list.currentRowChanged.connect(self._on_segment_row_changed)
        self.segment_list.itemClicked.connect(self._on_segment_item_clicked)
        segment_row.addWidget(self.segment_list, 1)

        segment_actions = QHBoxLayout()
        segment_actions.setSpacing(6)
        self.delete_segment_btn = PushButton("删除片段", self)
        self.delete_segment_btn.setEnabled(False)
        self.delete_segment_btn.setToolTip("删除当前选中的打码片段（可撤销）")
        self.delete_segment_btn.clicked.connect(self._on_delete_segment_clicked)
        segment_actions.addWidget(self.delete_segment_btn)

        self.llm_track_btn = PushButton("大模型追踪", self)
        self.llm_track_btn.setEnabled(False)
        self.llm_track_btn.setToolTip(
            "将锚定框选图与片段画面（5fps）发送给通义千问视觉模型，"
            "补充 OpenCV 跟丢或拉长入出点后的追踪"
        )
        self.llm_track_btn.clicked.connect(self._on_llm_track_clicked)
        segment_actions.addWidget(self.llm_track_btn)
        segment_row.addLayout(segment_actions)
        layout.addLayout(segment_row)

        for btn in (
            self.mark_in_btn,
            self.mark_out_btn,
            self.clear_marks_btn,
            self.delete_segment_btn,
            self.llm_track_btn,
        ):
            _disable_button_keyboard_activation(btn)

    def set_time_range_mode(self, enabled: bool):
        self._mark_row.setVisible(enabled)
        self.range_label.setVisible(enabled)
        if enabled:
            self._update_range_label()
        self.segment_track.set_mark_points(
            self._mark_in_ms if enabled else None,
            self._mark_out_ms if enabled else None,
        )

    def mark_in_ms(self) -> int | None:
        return self._mark_in_ms

    def mark_out_ms(self) -> int | None:
        return self._mark_out_ms

    def set_duration_ms(self, duration_ms: int):
        self._duration_ms = max(1, duration_ms)
        self.progress_slider.setRange(0, self._duration_ms)
        self.segment_track.set_duration_ms(self._duration_ms)
        self._clamp_marks()
        self._update_range_label()
        self._update_time_label(self.progress_slider.value())
        if self._selected_index >= 0:
            self._sync_segment_sliders()

    def duration_ms(self) -> int:
        return self._duration_ms

    def position_ms(self) -> int:
        return self.progress_slider.value()

    def set_position_ms(self, position_ms: int):
        self.progress_slider.setValue(max(0, min(self._duration_ms, position_ms)))

    def segments(self) -> list[MaskRegion]:
        return list(self._segments)

    def set_segments(self, segments: list[MaskRegion]):
        self._segments = list(segments)
        self.segment_track.set_segments(segments)
        if self._selected_index >= len(self._segments):
            self._selected_index = -1
            self.segment_list.blockSignals(True)
            self.segment_list.setCurrentRow(-1)
            self.segment_list.blockSignals(False)
        self.segment_track.set_selected_index(self._selected_index)
        self._refresh_segment_list()
        self._sync_segment_sliders()
        self._sync_segment_action_buttons()

    def _sync_segment_action_buttons(self):
        has_selection = 0 <= self._selected_index < len(self._segments)
        self.delete_segment_btn.setEnabled(has_selection)
        if not has_selection:
            self.llm_track_btn.setEnabled(False)
            return
        region = self._segments[self._selected_index]
        seed = region.seed_bbox_for_tracking()
        has_anchor = seed is not None or (region.nw > 0 and region.nh > 0)
        self.llm_track_btn.setEnabled(has_anchor and self._segment_times_adjusted)

    def _mark_in(self):
        self._mark_in_ms = self.position_ms()
        if self._mark_out_ms is not None and self._mark_out_ms <= self._mark_in_ms:
            self._mark_out_ms = None
        self._update_mark_display()

    def _mark_out(self):
        self._mark_out_ms = self.position_ms()
        if self._mark_in_ms is not None and self._mark_out_ms <= self._mark_in_ms:
            self._mark_in_ms = None
        self._update_mark_display()

    def _clear_marks(self):
        self._mark_in_ms = None
        self._mark_out_ms = None
        self._update_mark_display()

    def _clamp_marks(self):
        if self._mark_in_ms is not None:
            self._mark_in_ms = max(0, min(self._duration_ms, self._mark_in_ms))
        if self._mark_out_ms is not None:
            self._mark_out_ms = max(0, min(self._duration_ms, self._mark_out_ms))

    def _update_mark_display(self):
        self._clamp_marks()
        self.segment_track.set_mark_points(self._mark_in_ms, self._mark_out_ms)
        self._update_range_label()

    def _update_range_label(self):
        if self._mark_in_ms is not None and self._mark_out_ms is not None:
            text = (
                f"已设入出点：{format_time_ms(self._mark_in_ms)} → "
                f"{format_time_ms(self._mark_out_ms)}；在入点框选，再到出点框选更新位置"
            )
        elif self._mark_in_ms is not None:
            text = f"已设入点 {format_time_ms(self._mark_in_ms)}，请继续设置出点"
        elif self._mark_out_ms is not None:
            text = f"已设出点 {format_time_ms(self._mark_out_ms)}，请继续设置入点"
        else:
            text = (
                "请先设置入点和出点；在入点处框选，再在出点或其它时刻框选以添加关键帧"
            )
        self.range_label.setText(text)

    def _refresh_segment_list(self):
        current = self.segment_list.currentRow()
        self.segment_list.blockSignals(True)
        try:
            self.segment_list.clear()
            for segment in self._segments:
                self.segment_list.addItem(QListWidgetItem(segment.display_text()))
            if 0 <= self._selected_index < len(self._segments):
                self.segment_list.setCurrentRow(self._selected_index)
            elif 0 <= current < len(self._segments):
                self.segment_list.setCurrentRow(current)
        finally:
            self.segment_list.blockSignals(False)

    def _on_segment_row_changed(self, row: int):
        self._selected_index = row
        self._segment_times_adjusted = False
        self.segment_track.set_selected_index(row)
        self._sync_segment_sliders()
        self._sync_segment_action_buttons()
        self.segmentSelected.emit(row)

    def _on_segment_item_clicked(self, item: QListWidgetItem):
        row = self.segment_list.row(item)
        if row >= 0:
            self.segmentActivated.emit(row)

    def _on_delete_segment_clicked(self):
        if self._selected_index < 0 or self._selected_index >= len(self._segments):
            return
        self.segmentDeleteRequested.emit(self._selected_index)

    def _on_llm_track_clicked(self):
        if self._selected_index < 0 or self._selected_index >= len(self._segments):
            return
        self.llmTrackRequested.emit(self._selected_index)

    def _sync_segment_sliders(self):
        self._syncing_segment_sliders = True
        if self._selected_index < 0 or self._selected_index >= len(self._segments):
            self.segment_start_slider.setEnabled(False)
            self.segment_end_slider.setEnabled(False)
            self.segment_edit_label.setText("片段时长：选中列表中的片段后可调整")
        else:
            region = self._segments[self._selected_index]
            self.segment_start_slider.setEnabled(True)
            self.segment_end_slider.setEnabled(True)
            self.segment_start_slider.setRange(0, self._duration_ms)
            self.segment_end_slider.setRange(0, self._duration_ms)
            self.segment_start_slider.setValue(region.start_ms)
            self.segment_end_slider.setValue(max(region.start_ms + 34, region.end_ms))
            self.segment_edit_label.setText(
                f"片段时长：{region.label}  {format_time_ms(region.start_ms)} → "
                f"{format_time_ms(region.end_ms)}"
            )
        self._syncing_segment_sliders = False

    def _on_segment_start_changed(self, start_ms: int):
        if self._syncing_segment_sliders or self._selected_index < 0:
            return
        end_ms = self.segment_end_slider.value()
        if start_ms >= end_ms:
            start_ms = max(0, end_ms - 34)
            self._syncing_segment_sliders = True
            self.segment_start_slider.setValue(start_ms)
            self._syncing_segment_sliders = False
        self._segment_times_adjusted = True
        self._sync_segment_action_buttons()
        self.segmentTimeChanged.emit(self._selected_index, start_ms, end_ms)

    def _on_segment_end_changed(self, end_ms: int):
        if self._syncing_segment_sliders or self._selected_index < 0:
            return
        start_ms = self.segment_start_slider.value()
        if end_ms <= start_ms:
            end_ms = min(self._duration_ms, start_ms + 34)
            self._syncing_segment_sliders = True
            self.segment_end_slider.setValue(end_ms)
            self._syncing_segment_sliders = False
        self._segment_times_adjusted = True
        self._sync_segment_action_buttons()
        self.segmentTimeChanged.emit(self._selected_index, start_ms, end_ms)

    def _on_position_changed(self, position_ms: int):
        self._update_time_label(position_ms)
        self.positionChanged.emit(position_ms)

    def _update_time_label(self, position_ms: int):
        self.time_label.setText(
            f"{format_time_ms(position_ms)} / {format_time_ms(self._duration_ms)}"
        )


class MaskEditorWorkspace(QWidget):
    """打码主工作区：剧集列表 + 预览 + 控制面板 + 时间轴。"""

    selectionFinished = Signal(QRectF)
    maskTypeChanged = Signal(str)
    intensityChanged = Signal(int)
    applyModeChanged = Signal(str)
    positionChanged = Signal(int)
    episodeChanged = Signal(int, str)
    regionsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._current_path: str | None = None
        self._episode_states: dict[str, list[MaskRegion]] = {}
        self._history = MaskEditHistory()
        self._syncing_timeline = False
        self._pending_tracking_index: int | None = None
        self._episode_index = -1
        self._episode_load_token = 0
        self._track_cancel_event: threading.Event | None = None
        self._llm_anchor_dialog: LlmAnchorTrackingDialog | None = None
        self._init_ui()
        self._bind_shortcuts()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        top_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        top_splitter.setChildrenCollapsible(False)

        self.episode_list = EpisodeListWidget(self)
        self.episode_list.episodeSelected.connect(self._on_episode_selected)
        top_splitter.addWidget(self.episode_list)

        preview_column = QVBoxLayout()
        preview_column.setSpacing(6)

        preview_header = QHBoxLayout()
        preview_header.addWidget(SubtitleLabel("视频预览", self))
        preview_header.addWidget(BodyLabel("播放时仅在对应时间段显示打码框", self))
        preview_header.addStretch(1)
        self.undo_btn = PushButton("撤销", self)
        self.redo_btn = PushButton("重做", self)
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn.clicked.connect(self.redo)
        preview_header.addWidget(self.undo_btn)
        preview_header.addWidget(self.redo_btn)
        self.play_toggle_btn = PushButton("播放", self)
        self.play_toggle_btn.clicked.connect(self._toggle_playback)
        preview_header.addWidget(self.play_toggle_btn)
        for btn in (self.undo_btn, self.redo_btn, self.play_toggle_btn):
            _disable_button_keyboard_activation(btn)
        preview_column.addLayout(preview_header)

        self.preview = VideoPreviewPlayer(self)
        self.preview.setMinimumHeight(420)
        self.preview.selectionFinished.connect(self._on_region_selected)
        self.preview.selectionFinished.connect(self.selectionFinished.emit)
        self.preview.regionClicked.connect(self._on_preview_region_clicked)
        self.preview.emptyClicked.connect(self._on_preview_empty_clicked)
        self.preview.pausedChanged.connect(self._sync_play_button)
        self.preview.positionChanged.connect(self._on_player_position)
        self.preview.durationChanged.connect(self._on_player_duration)
        preview_column.addWidget(self.preview, 1)

        preview_host = QWidget(self)
        preview_host.setLayout(preview_column)
        top_splitter.addWidget(preview_host)

        self.control_panel = MaskControlPanel(self)
        self.control_panel.maskTypeChanged.connect(self.maskTypeChanged.emit)
        self.control_panel.intensityChanged.connect(self.intensityChanged.emit)
        top_splitter.addWidget(self.control_panel)

        top_splitter.setStretchFactor(0, 0)
        top_splitter.setStretchFactor(1, 1)
        top_splitter.setStretchFactor(2, 0)
        top_splitter.setSizes([140, 900, 260])

        layout.addWidget(top_splitter, 1)

        layout.addWidget(SubtitleLabel("时间轴", self))
        self.timeline = MaskTimelineWidget(self)
        self.timeline.positionChanged.connect(self._on_timeline_seek)
        self.timeline.positionChanged.connect(self.positionChanged.emit)
        self.timeline.segmentTimeChanged.connect(self._on_segment_time_changed)
        self.timeline.segmentSelected.connect(self._on_segment_selected)
        self.timeline.segmentActivated.connect(self._on_segment_activated)
        self.timeline.segmentDeleteRequested.connect(self._on_segment_deleted)
        self.timeline.llmTrackRequested.connect(self._on_llm_track_requested)
        layout.addWidget(self.timeline)

        self.control_panel.track_btn.clicked.connect(self._on_start_tracking_clicked)
        self.timeline.set_time_range_mode(False)
        self.applyModeChanged.emit(MODE_TRACKING)
        self._sync_undo_buttons()
        self._sync_track_button()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _refocus_editor(self):
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _select_region_index(self, index: int):
        """同步预览高亮、时间轴列表与待追踪目标。"""
        if index < 0:
            self._pending_tracking_index = None
            self.preview.set_selected_region_index(-1)
            self.timeline._selected_index = -1
            self.timeline.segment_list.blockSignals(True)
            self.timeline.segment_list.setCurrentRow(-1)
            self.timeline.segment_list.blockSignals(False)
            self.timeline.segment_track.set_selected_index(-1)
            self.timeline._sync_segment_action_buttons()
            self._sync_track_button()
            return
        regions = self._history.current()
        if index >= len(regions):
            return
        self._pending_tracking_index = index
        self.preview.set_selected_region_index(index)
        self.timeline._selected_index = index
        self.timeline.segment_list.blockSignals(True)
        self.timeline.segment_list.setCurrentRow(index)
        self.timeline.segment_list.blockSignals(False)
        self.timeline.segment_track.set_selected_index(index)
        self.timeline._sync_segment_action_buttons()
        self._sync_track_button()

    def _on_preview_region_clicked(self, region_index: int):
        self._select_region_index(region_index)

    def _on_preview_empty_clicked(self):
        self._select_region_index(-1)

    def _on_segment_selected(self, index: int):
        if index >= 0:
            self._select_region_index(index)
        else:
            self._select_region_index(-1)

    def _on_segment_activated(self, index: int):
        if index >= 0:
            self._select_region_index(index)
            regions = self._history.current()
            if index < len(regions):
                self._seek_to_ms(regions[index].start_ms)
        else:
            self._select_region_index(-1)

    def _seek_to_ms(self, position_ms: int):
        self.preview.pause()
        self._syncing_timeline = True
        self.timeline.set_position_ms(position_ms)
        self.preview.set_position_ms(position_ms)
        self.preview.refresh_regions_at(position_ms)
        self._syncing_timeline = False

    def _on_segment_deleted(self, index: int):
        regions = self._history.current()
        if index < 0 or index >= len(regions):
            return
        new_regions = [region for i, region in enumerate(regions) if i != index]
        if self._pending_tracking_index == index:
            self._pending_tracking_index = None
        elif self._pending_tracking_index is not None and self._pending_tracking_index > index:
            self._pending_tracking_index -= 1
        self._apply_regions(new_regions)
        self._persist_current_episode()

    def _resolve_tracking_target(self) -> tuple[int, MaskRegion] | None:
        if self._pending_tracking_index is None:
            return None
        regions = self._history.current()
        idx = self._pending_tracking_index
        if 0 <= idx < len(regions):
            return idx, regions[idx]
        return None

    def _sync_track_button(self):
        btn = self.control_panel.track_btn
        target = self._resolve_tracking_target()
        regions = self._history.current()
        if target is None:
            btn.setEnabled(False)
            btn.setText("开始追踪")
            if regions:
                btn.setToolTip(
                    "画面上有多个框时，请先点击要追踪的那一个，再点「开始追踪」"
                )
            else:
                btn.setToolTip("请先在暂停状态下于画面上框选要追踪的目标")
            return
        _idx, region = target
        tracked = len(region.track_keyframes) > 1
        seed = region.seed_bbox_for_tracking()
        btn.setEnabled(seed is not None)
        btn.setText("重新追踪" if tracked else "开始追踪")
        if seed is None:
            btn.setToolTip(
                f"「{region.label}」的入点已超出已有追踪范围，请暂停到入点并重新框选目标"
            )
        else:
            btn.setToolTip(
                f"对选中的「{region.label}」从入点 {format_time_ms(region.start_ms)} "
                f"执行 OpenCV CSRT 追踪（种子框与预览一致）"
            )

    def _bind_shortcuts(self):
        shortcut_ctx = Qt.ShortcutContext.WidgetWithChildrenShortcut
        QShortcut(QKeySequence.StandardKey.Undo, self, self.undo)
        QShortcut(QKeySequence.StandardKey.Redo, self, self.redo)

        def bind(keys, slot):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(shortcut_ctx)
            shortcut.activated.connect(slot)

        bind(Qt.Key.Key_Space, self._toggle_playback_if_allowed)
        bind(Qt.Key.Key_Left, lambda: self._step_playhead_frames(-1))
        bind(Qt.Key.Key_Right, lambda: self._step_playhead_frames(1))
        bind("Shift+Left", lambda: self._step_playhead_ms(-5000))
        bind("Shift+Right", lambda: self._step_playhead_ms(5000))

    def _shortcut_blocked(self) -> bool:
        focus = QApplication.focusWidget()
        if focus is None:
            return False
        if isinstance(focus, (QLineEdit, QTextEdit, QPlainTextEdit)):
            return True
        return isinstance(focus, QComboBox) and focus.isEditable()

    def _toggle_playback_if_allowed(self):
        if self._shortcut_blocked():
            return
        self._toggle_playback()

    def _step_playhead_frames(self, direction: int):
        if self._shortcut_blocked() or not self._current_path:
            return
        self._step_playhead_ms(self.preview.frame_duration_ms() * direction)

    def _step_playhead_ms(self, delta_ms: int):
        if self._shortcut_blocked() or not self._current_path:
            return
        duration = self.timeline.duration_ms()
        new_pos = max(0, min(duration, self.timeline.position_ms() + delta_ms))
        self._seek_to_ms(new_pos)

    def load_episodes(self, video_paths: list[str]):
        self._cancel_background_tracking()
        self._episode_states.clear()
        self._history.reset()
        self._episode_index = -1
        if video_paths:
            self.episode_list.set_episodes(video_paths)
            self._load_episode(0, video_paths[0], save_previous=False)
        else:
            self.episode_list.set_episodes([])
            self._current_path = None
            self.timeline.set_duration_ms(60_000)
            self.timeline.set_segments([])

    def set_duration_ms(self, duration_ms: int):
        self.timeline.set_duration_ms(duration_ms)

    def set_intensity(self, value: int):
        self.control_panel.set_intensity(value)

    def intensity(self) -> int:
        return self.control_panel.intensity()

    def set_edit_overlay_visible(self, visible: bool):
        self.preview.set_edit_overlay_visible(visible)

    def current_regions(self) -> list[MaskRegion]:
        return self._history.current()

    def undo(self):
        regions = self._history.undo()
        if regions is None:
            return
        self._apply_regions(regions, record_undo=False)
        self._persist_current_episode()

    def redo(self):
        regions = self._history.redo()
        if regions is None:
            return
        self._apply_regions(regions, record_undo=False)
        self._persist_current_episode()

    def _sync_undo_buttons(self):
        self.undo_btn.setEnabled(self._history.can_undo())
        self.redo_btn.setEnabled(self._history.can_redo())

    def _toggle_playback(self):
        self.preview.toggle_playback()

    def _sync_play_button(self, paused: bool):
        self.play_toggle_btn.setText("播放" if paused else "暂停")

    def _cancel_background_tracking(self):
        if self._track_cancel_event is not None:
            self._track_cancel_event.set()
        self._episode_load_token += 1
        self._close_llm_anchor_dialog()
        self._sync_track_button()
        self._sync_llm_track_button()

    def _close_llm_anchor_dialog(self):
        if self._llm_anchor_dialog is None:
            return
        self._llm_anchor_dialog.close()
        self._llm_anchor_dialog.deleteLater()
        self._llm_anchor_dialog = None

    def _on_episode_selected(self, index: int, path: str):
        if index == self._episode_index and path == self._current_path:
            return
        self.episodeChanged.emit(index, path)
        self._load_episode(index, path)

    def _persist_current_episode(self):
        if self._current_path:
            self._episode_states[self._current_path] = self._history.current()

    def _load_episode(self, index: int, path: str, *, save_previous: bool = True):
        if self.episode_list.list.currentRow() != index:
            return

        path_obj = Path(path)
        if not path_obj.is_file():
            show_dialog(
                self,
                f"找不到视频文件：{path_obj.name}\n请检查剧集文件夹。",
                "剧集切换",
            )
            if 0 <= self._episode_index < self.episode_list.list.count():
                self.episode_list.select_row(self._episode_index)
            return

        previous_index = self._episode_index

        if save_previous and self._current_path:
            self._persist_current_episode()

        self._cancel_background_tracking()
        load_token = self._episode_load_token
        self._episode_index = index
        self._current_path = path

        self._syncing_timeline = True
        self.timeline.set_position_ms(0)
        self._syncing_timeline = False

        try:
            self.preview.load(str(path_obj))
        except OSError as exc:
            show_dialog(self, f"无法加载视频：{exc}", "剧集切换")
            self._episode_index = previous_index
            if 0 <= previous_index < self.episode_list.list.count():
                self.episode_list.select_row(previous_index)
            return

        if load_token != self._episode_load_token:
            return

        regions = self._episode_states.get(path, [])
        self._history.reset(regions)
        self._pending_tracking_index = None
        self._apply_regions(regions, record_undo=False)

    def _apply_regions(self, regions: list[MaskRegion], *, record_undo: bool = True):
        self._history.set_current(regions, record_undo=record_undo)
        if self._pending_tracking_index is not None and self._pending_tracking_index >= len(
            regions
        ):
            self._pending_tracking_index = None
        self.preview.set_mask_regions(regions)
        if self._pending_tracking_index is not None:
            self.preview.set_selected_region_index(self._pending_tracking_index)
        else:
            self.preview.set_selected_region_index(-1)
        self.timeline.set_segments(regions)
        self._sync_undo_buttons()
        self._sync_track_button()
        self.regionsChanged.emit()

    def _on_player_position(self, position_ms: int):
        if self._syncing_timeline:
            return
        self._syncing_timeline = True
        self.timeline.set_position_ms(position_ms)
        self._syncing_timeline = False

    def _on_player_duration(self, duration_ms: int):
        if duration_ms > 0:
            self.timeline.set_duration_ms(duration_ms)

    def _on_timeline_seek(self, position_ms: int):
        if self._syncing_timeline:
            return
        self._syncing_timeline = True
        self.preview.set_position_ms(position_ms)
        self.preview.refresh_regions_at(position_ms)
        self._syncing_timeline = False

    def _on_segment_time_changed(self, index: int, start_ms: int, end_ms: int):
        regions = self._history.current()
        if index < 0 or index >= len(regions):
            return
        updated = regions[index].with_segment_times(start_ms, end_ms)
        new_regions = list(regions)
        new_regions[index] = updated
        self._apply_regions(new_regions)
        self._persist_current_episode()

    def _on_region_selected(self, normalized_rect: QRectF):
        if not self._current_path:
            show_dialog(self, "请先加载视频。", "智能追踪")
            return

        playhead_ms = self.timeline.position_ms()
        start_ms, end_ms = compute_region_time_range(
            playhead_ms,
            self.timeline.duration_ms(),
            MODE_TRACKING,
        )
        nx, ny, nw, nh = (
            normalized_rect.x(),
            normalized_rect.y(),
            normalized_rect.width(),
            normalized_rect.height(),
        )

        label_index = len(self._history.current()) + 1
        region = MaskRegion(
            nx=nx,
            ny=ny,
            nw=nw,
            nh=nh,
            start_ms=start_ms,
            end_ms=end_ms,
            label=f"区域{label_index}",
            mask_type=self.control_panel.mask_type(),
            intensity=self.control_panel.intensity(),
            mode=MODE_TRACKING,
        ).clamped()
        region = region.upsert_keyframe(
            playhead_ms, region.nx, region.ny, region.nw, region.nh
        )

        new_regions = [*self._history.current(), region]
        region_index = len(new_regions) - 1
        self._apply_regions(new_regions)
        self._persist_current_episode()
        self._select_region_index(region_index)

    def _on_start_tracking_clicked(self):
        if not self._current_path:
            show_dialog(self, "请先加载视频后再追踪。", "智能追踪")
            return
        target = self._resolve_tracking_target()
        if target is None:
            regions = self._history.current()
            if regions:
                show_dialog(
                    self,
                    "请先在画面上点击要追踪的框（或时间轴列表中选中片段），再点击「开始追踪」。",
                    "智能追踪",
                )
            else:
                show_dialog(
                    self,
                    "请暂停视频，在画面上框选要追踪的目标后再点击「开始追踪」。",
                    "智能追踪",
                )
            return
        row, region = target
        self._select_region_index(row)
        self._start_object_tracking(row, region)

    def _start_object_tracking(self, region_index: int, region: MaskRegion):
        video_path = self._current_path
        if not video_path:
            return

        seed = region.seed_bbox_for_tracking()
        if seed is None:
            show_dialog(
                self,
                "当前入点处没有有效的框选目标。\n请暂停到入点位置，在画面上重新框选后再追踪。",
                "智能追踪",
            )
            self._sync_track_button()
            return
        nx, ny, nw, nh = seed

        self.control_panel.track_btn.setEnabled(False)
        self.control_panel.track_btn.setText("追踪中…")
        self._refocus_editor()

        cancel_event = threading.Event()
        self._track_cancel_event = cancel_event
        load_token = self._episode_load_token

        def on_success(keyframes: list[tuple[int, float, float, float, float]]):
            if load_token != self._episode_load_token:
                self._sync_track_button()
                return
            regions = self._history.current()
            if region_index >= len(regions):
                self._sync_track_button()
                return
            updated = regions[region_index].with_tracking_keyframes(keyframes)
            new_regions = list(regions)
            new_regions[region_index] = updated
            self._apply_regions(new_regions, record_undo=False)
            self._persist_current_episode()
            self._sync_track_button()

        def on_error(message: str):
            if load_token != self._episode_load_token:
                self._sync_track_button()
                return
            show_dialog(
                self,
                f"智能追踪未完成：{message}\n已保留初始框选，可调整框后重试。",
                "提示",
            )
            self._sync_track_button()

        task_manager.submit_task(
            track_object_in_video,
            kwargs={
                "video_path": video_path,
                "start_ms": region.start_ms,
                "end_ms": region.end_ms,
                "nx": nx,
                "ny": ny,
                "nw": nw,
                "nh": nh,
                "should_cancel": cancel_event.is_set,
            },
            on_success=on_success,
            on_error=on_error,
        )

    def _anchor_for_llm_tracking(
        self, region: MaskRegion
    ) -> tuple[int, float, float, float, float] | None:
        """返回锚定时刻与归一化框（用户最初框选）。"""
        if region.track_keyframes:
            anchor_time_ms, nx, ny, nw, nh = sorted(
                region.track_keyframes, key=lambda item: item[0]
            )[0]
            if nw > 0 and nh > 0:
                return anchor_time_ms, nx, ny, nw, nh
        if region.nw > 0 and region.nh > 0:
            return region.start_ms, region.nx, region.ny, region.nw, region.nh
        seed = region.seed_bbox_for_tracking()
        if seed is None:
            return None
        return region.start_ms, *seed

    def _on_llm_track_requested(self, index: int):
        if not self._current_path:
            show_dialog(self, "请先加载视频后再使用大模型追踪。", "大模型追踪")
            return
        regions = self._history.current()
        if index < 0 or index >= len(regions):
            return
        region = regions[index]
        anchor = self._anchor_for_llm_tracking(region)
        if anchor is None:
            show_dialog(
                self,
                "当前片段缺少锚定框选，请暂停到入点并重新框选目标。",
                "大模型追踪",
            )
            return
        anchor_time_ms, anchor_nx, anchor_ny, anchor_nw, anchor_nh = anchor
        self._select_region_index(index)

        self.timeline.llm_track_btn.setEnabled(False)
        self.timeline.llm_track_btn.setText("大模型追踪中…")
        self._refocus_editor()

        self._close_llm_anchor_dialog()
        anchor_preview = _build_anchor_preview_pixmap(
            self._current_path,
            anchor_time_ms,
            anchor_nx,
            anchor_ny,
            anchor_nw,
            anchor_nh,
        )
        self._llm_anchor_dialog = LlmAnchorTrackingDialog(
            self,
            region_label=region.label or f"区域{index + 1}",
            anchor_time_ms=anchor_time_ms,
            preview=anchor_preview,
        )
        self._llm_anchor_dialog.show()

        cancel_event = threading.Event()
        self._track_cancel_event = cancel_event
        load_token = self._episode_load_token

        def on_success(keyframes: list[tuple[int, float, float, float, float]]):
            self._close_llm_anchor_dialog()
            if load_token != self._episode_load_token:
                self._sync_llm_track_button()
                return
            current = self._history.current()
            if index >= len(current):
                self._sync_llm_track_button()
                return
            updated = current[index].with_tracking_keyframes(keyframes)
            new_regions = list(current)
            new_regions[index] = updated
            self._apply_regions(new_regions, record_undo=False)
            self._persist_current_episode()
            self.timeline._segment_times_adjusted = False
            self._sync_llm_track_button()

        def on_error(message: str):
            self._close_llm_anchor_dialog()
            if load_token != self._episode_load_token:
                self._sync_llm_track_button()
                return
            show_dialog(
                self,
                f"大模型追踪未完成：{message}\n已保留现有追踪结果，可调整后重试。",
                "提示",
            )
            self._sync_llm_track_button()

        task_manager.submit_task(
            track_object_with_llm,
            kwargs={
                "video_path": self._current_path,
                "start_ms": region.start_ms,
                "end_ms": region.end_ms,
                "anchor_time_ms": anchor_time_ms,
                "anchor_nx": anchor_nx,
                "anchor_ny": anchor_ny,
                "anchor_nw": anchor_nw,
                "anchor_nh": anchor_nh,
                "existing_keyframes": list(region.track_keyframes),
                "should_cancel": cancel_event.is_set,
            },
            on_success=on_success,
            on_error=on_error,
        )

    def _sync_llm_track_button(self):
        btn = self.timeline.llm_track_btn
        btn.setText("大模型追踪")
        self.timeline._sync_segment_action_buttons()


class ThreeStageMaskWidget(QWidget):
    """三段式视频打码工作区（框选 → 预览打码 → 导出）。"""

    stageChanged = Signal(int)
    confirmed = Signal(str)
    cancelled = Signal()
    maskTypeChanged = Signal(str)
    intensityChanged = Signal(int)
    applyModeChanged = Signal(str)
    selectionFinished = Signal(QRectF)
    positionChanged = Signal(int)

    STAGE_KEYS = ("stage_select", "stage_preview")
    STAGE_LABELS = ("① 框选区域", "② 打码预览")

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stage_index = 0
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.segment = SegmentedWidget(self)
        for key, label in zip(self.STAGE_KEYS, self.STAGE_LABELS):
            self.segment.addItem(key, label)
        self.segment.currentItemChanged.connect(self._on_segment_changed)
        layout.addWidget(self.segment)

        self.stack = QStackedWidget(self)
        self.editor = MaskEditorWorkspace(self)
        self.stack.addWidget(self.editor)                       # index 0 — 框选区域
        self.masked_preview = MaskedVideoPreview(self)
        self.stack.addWidget(self.masked_preview)               # index 1 — 打码预览
        layout.addWidget(self.stack, 1)

        self.editor.maskTypeChanged.connect(self.maskTypeChanged.emit)
        self.editor.intensityChanged.connect(self.intensityChanged.emit)
        self.editor.applyModeChanged.connect(self.applyModeChanged.emit)
        self.editor.selectionFinished.connect(self.selectionFinished.emit)
        self.editor.positionChanged.connect(self.positionChanged.emit)

        nav = QHBoxLayout()
        nav.setSpacing(8)
        nav.addStretch(1)
        self.prev_btn = PushButton("上一步", self)
        self.next_btn = PrimaryPushButton("下一步", self)
        self.export_btn = PrimaryPushButton("导出打码视频", self)
        self.cancel_btn = PushButton("取消", self)
        for btn in (self.prev_btn, self.next_btn, self.export_btn, self.cancel_btn):
            _disable_button_keyboard_activation(btn)
        self.export_btn.hide()
        self.prev_btn.clicked.connect(self._go_prev)
        self.next_btn.clicked.connect(self._go_next)
        self.cancel_btn.clicked.connect(self.cancelled.emit)
        self.export_btn.clicked.connect(self._on_export_clicked)
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.next_btn)
        nav.addWidget(self.export_btn)
        nav.addWidget(self.cancel_btn)
        layout.addLayout(nav)

        self._sync_nav()
        self._sync_stage_overlay()

    def set_duration_ms(self, duration_ms: int):
        self.editor.set_duration_ms(duration_ms)

    def set_intensity(self, value: int):
        self.editor.set_intensity(value)

    def intensity(self) -> int:
        return self.editor.intensity()

    def load_episodes(self, video_paths: list[str]):
        self.editor.load_episodes(video_paths)

    def _on_segment_changed(self, route_key: str):
        try:
            index = self.STAGE_KEYS.index(route_key)
        except ValueError:
            index = 0
        self._set_stage(index)

    def _set_stage(self, index: int):
        index = max(0, min(index, len(self.STAGE_KEYS) - 1))
        self._stage_index = index
        self.stack.setCurrentIndex(index)
        if self.segment.currentItem() != self.STAGE_KEYS[index]:
            self.segment.setCurrentItem(self.STAGE_KEYS[index])
        self._sync_nav()
        self._sync_stage_overlay()
        self.stageChanged.emit(index)

        if index == 1:
            self._sync_preview()
            self.masked_preview.pause()

    def _sync_stage_overlay(self):
        show_overlay = self._stage_index == 0
        self.editor.set_edit_overlay_visible(show_overlay)

    def _sync_nav(self):
        at_preview = self._stage_index == 1
        self.prev_btn.setEnabled(self._stage_index > 0)
        self.next_btn.setVisible(self._stage_index == 0)
        self.export_btn.setVisible(at_preview)

    def _go_prev(self):
        self._set_stage(self._stage_index - 1)

    def _go_next(self):
        self._set_stage(self._stage_index + 1)

    def _on_export_clicked(self):
        export_dir = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if export_dir:
            self.confirmed.emit(export_dir)

    def _sync_preview(self):
        self.editor._persist_current_episode()
        episodes = []
        for path in self.editor.episode_list._paths:
            regions = self.editor._episode_states.get(path, [])
            episodes.append((path, regions))
        if episodes:
            self.masked_preview.load_episodes(episodes)
            self.masked_preview.select_episode(max(0, self.editor._episode_index))
        else:
            self.masked_preview.clear()

    def reset_stages(self):
        self._set_stage(0)
