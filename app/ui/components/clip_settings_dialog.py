"""自动化剪辑页「设置」弹框：片尾去卡等选项。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, SwitchButton

from app.common.config import cfg


class ClipSettingsDialog(QDialog):
    """剪辑相关开关。确定后由调用方写入 cfg。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)
        root.setSpacing(12)

        tip = BodyLabel(
            "渲染时生效。关闭后保持片尾原样，不检测、不裁切。",
            self,
        )
        tip.setWordWrap(True)
        root.addWidget(tip)

        form = QFormLayout()
        form.setSpacing(10)

        row = QHBoxLayout()
        self._trim_switch = SwitchButton(self)
        self._trim_switch.setOnText("开")
        self._trim_switch.setOffText("关")
        self._trim_switch.setChecked(bool(cfg.clip_trim_ep1_continued.value))
        self._trim_switch.setToolTip(
            "检测到第一集片尾「未完待续」时自动裁掉最后 3 秒；未检测到则不裁"
        )
        row.addWidget(self._trim_switch)
        row.addStretch(1)
        form.addRow("去掉未完待续：", row)
        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def result_trim_ep1_continued(self) -> bool:
        return bool(self._trim_switch.isChecked())
