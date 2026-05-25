from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
from qfluentwidgets import BodyLabel, MaskDialogBase, PrimaryPushButton, PushButton, SubtitleLabel

from app.data.models.drama_project import DramaProject
from app.ui.components.three_stage_mask_widget import ThreeStageMaskWidget


class MaskEditDialog(MaskDialogBase):
    """单部剧的打码弹窗：覆盖主窗口，内含三段式打码组件。"""

    finished_ok = Signal(str)

    def __init__(self, project: DramaProject, parent=None):
        self.project = project
        super().__init__(parent=parent)
        self._init_ui()

    def _init_ui(self):
        self.widget.setFixedSize(920, 680)
        layout = QVBoxLayout(self.widget)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(8)

        layout.addWidget(SubtitleLabel(self.project.name, self.widget))
        layout.addWidget(
            BodyLabel(
                f"共 {self.project.episode_count} 集 · 目录: {self.project.folder_path or '未设置'}",
                self.widget,
            )
        )

        self.mask_widget = ThreeStageMaskWidget(self.widget)
        layout.addWidget(self.mask_widget, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        cancel_btn = PushButton("取消", self.widget)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self.mask_widget.confirmed.connect(self._on_confirm)

    def _on_confirm(self):
        self.finished_ok.emit(self.project.id)
        self.accept()

    def showEvent(self, event):
        self.mask_widget.reset_stages()
        super().showEvent(event)
