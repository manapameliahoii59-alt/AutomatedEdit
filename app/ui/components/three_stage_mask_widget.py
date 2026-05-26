from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, PrimaryPushButton, PushButton, SegmentedWidget, SubtitleLabel


class ThreeStageMaskWidget(QWidget):
    """三段式视频打码工作区（框选 → 预览打码 → 确认导出）。"""

    stageChanged = Signal(int)
    confirmed = Signal()

    STAGE_KEYS = ("stage_select", "stage_preview", "stage_export")
    STAGE_LABELS = ("① 框选区域", "② 打码预览", "③ 确认导出")

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
        for i, title in enumerate(self.STAGE_LABELS):
            self.stack.addWidget(self._create_stage_page(i, title))
        layout.addWidget(self.stack, 1)

        nav = QHBoxLayout()
        nav.addStretch(1)
        self.prev_btn = PushButton("上一步", self)
        self.next_btn = PrimaryPushButton("下一步", self)
        self.confirm_btn = PrimaryPushButton("确认完成", self)
        self.confirm_btn.hide()
        self.prev_btn.clicked.connect(self._go_prev)
        self.next_btn.clicked.connect(self._go_next)
        self.confirm_btn.clicked.connect(self.confirmed.emit)
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.next_btn)
        nav.addWidget(self.confirm_btn)
        layout.addLayout(nav)

        self._sync_nav()

    def _create_stage_page(self, index: int, title: str) -> QWidget:
        page = QWidget(self)
        page_layout = QVBoxLayout(page)
        page_layout.addWidget(SubtitleLabel(title, page))
        hint = (
            "在此嵌入视频播放器与框选工具（阶段一）。"
            if index == 0
            else "在此展示打码效果预览（阶段二）。"
            if index == 1
            else "核对输出路径与集数后确认导出（阶段三）。"
        )
        page_layout.addWidget(BodyLabel(hint, page))
        page_layout.addWidget(QLabel("（占位：接入你的打码/预览/导出组件）", page))
        page_layout.addStretch(1)
        return page

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
        self.stageChanged.emit(index)

    def _sync_nav(self):
        last = self._stage_index >= len(self.STAGE_KEYS) - 1
        self.prev_btn.setEnabled(self._stage_index > 0)
        self.next_btn.setVisible(not last)
        self.confirm_btn.setVisible(last)

    def _go_prev(self):
        self._set_stage(self._stage_index - 1)

    def _go_next(self):
        self._set_stage(self._stage_index + 1)

    def reset_stages(self):
        self._set_stage(0)
