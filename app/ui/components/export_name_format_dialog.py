"""文件名日期 / 序号格式弹框。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel

from app.common.export_paths import (
    EXPORT_DATE_FORMAT_CHOICES,
    EXPORT_SEQ_FORMAT_CHOICES,
    build_clip_export_filename,
    clamp_export_date_format,
    clamp_export_seq_format,
)
from app.common.config import cfg


class ExportNameFormatDialog(QDialog):
    """自定义成片文件名中的日期与序号。确定后由调用方写入 cfg。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        project_name: str = "剧名示例",
        tag: str = "",
    ):
        super().__init__(parent)
        self.setWindowTitle("文件名格式")
        self.setMinimumWidth(420)
        self._project_name = project_name
        self._tag = tag

        root = QVBoxLayout(self)
        root.setSpacing(12)

        tip = BodyLabel(
            "只影响新渲染的文件名。标识仍在主界面填写。",
            self,
        )
        tip.setWordWrap(True)
        root.addWidget(tip)

        form = QFormLayout()
        form.setSpacing(10)

        self._date_combo = QComboBox(self)
        for value, label in EXPORT_DATE_FORMAT_CHOICES:
            self._date_combo.addItem(label, value)
        date_idx = self._date_combo.findData(
            clamp_export_date_format(cfg.clip_export_date_format.value)
        )
        if date_idx >= 0:
            self._date_combo.setCurrentIndex(date_idx)

        self._seq_combo = QComboBox(self)
        for value, label in EXPORT_SEQ_FORMAT_CHOICES:
            self._seq_combo.addItem(label, value)
        seq_idx = self._seq_combo.findData(
            clamp_export_seq_format(cfg.clip_export_seq_format.value)
        )
        if seq_idx >= 0:
            self._seq_combo.setCurrentIndex(seq_idx)

        form.addRow("日期：", self._date_combo)
        form.addRow("序号：", self._seq_combo)
        root.addLayout(form)

        self._preview = BodyLabel("", self)
        self._preview.setWordWrap(True)
        root.addWidget(self._preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._date_combo.currentIndexChanged.connect(self._refresh_preview)
        self._seq_combo.currentIndexChanged.connect(self._refresh_preview)
        self._refresh_preview()

    def result_date_format(self) -> str:
        return clamp_export_date_format(self._date_combo.currentData())

    def result_seq_format(self) -> str:
        return clamp_export_seq_format(self._seq_combo.currentData())

    def _refresh_preview(self, *_args) -> None:
        filename = build_clip_export_filename(
            self._project_name,
            1,
            tag=self._tag,
            date_format=self.result_date_format(),
            seq_format=self.result_seq_format(),
        )
        self._preview.setText(f"效果：{filename}.mp4")
