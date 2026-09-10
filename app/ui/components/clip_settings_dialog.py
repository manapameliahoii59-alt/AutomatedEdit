"""自动化剪辑页「设置」弹框：片尾去卡、成片分辨率等选项。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import BodyLabel, ComboBox, SwitchButton

from app.common.config import cfg
from app.data.services.render_service import (
    RESOLUTION_CHOICES,
    RenderService,
)


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

        row_gpu = QHBoxLayout()
        self._gpu_switch = SwitchButton(self)
        self._gpu_switch.setOnText("开")
        self._gpu_switch.setOffText("关")
        self._gpu_switch.setChecked(bool(cfg.encode_enable_gpu.value))
        self._gpu_switch.setToolTip(
            "开启后自动检测显卡硬件加速（支持 NVIDIA 独显、AMD 独显/核显、Intel 核显），大幅提高渲染剪辑速度；\n"
            "关闭后强制使用纯 CPU 软编码。"
        )
        row_gpu.addWidget(self._gpu_switch)
        row_gpu.addStretch(1)
        form.addRow("显卡加速检测：", row_gpu)

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

        row_auto_select = QHBoxLayout()
        self._auto_select_switch = SwitchButton(self)
        self._auto_select_switch.setOnText("开")
        self._auto_select_switch.setOffText("关")
        self._auto_select_switch.setChecked(bool(cfg.clip_auto_select_after_import.value))
        self._auto_select_switch.setToolTip(
            "开启后，点击「导入剧目」导入完成后自动全选列表中剧目，方便直接执行一键执行或批量处理；\n"
            "关闭后导入保持未勾选状态。"
        )
        row_auto_select.addWidget(self._auto_select_switch)
        row_auto_select.addStretch(1)
        form.addRow("导入后自动全选：", row_auto_select)

        self._resolution_combo = ComboBox(self)
        for value, label in RESOLUTION_CHOICES:
            self._resolution_combo.addItem(label, userData=value)
        cur = RenderService.normalize_render_resolution(
            str(cfg.encode_output_resolution.value)
        )
        idx = self._resolution_combo.findData(cur)
        if idx >= 0:
            self._resolution_combo.setCurrentIndex(idx)
        self._resolution_combo.setToolTip(
            "横屏成片 1280x720 / 1920x1080，竖屏 720x1280 / 1080x1920。\n"
            "1080p 更清晰但成片体积约 2 倍、渲染更久；跟随原片按片源尺寸输出。\n"
            "画面文字字号按 720p 基准自动同比缩放。更改后新渲染重建缓存，旧缓存不删除。"
        )
        form.addRow("成片分辨率：", self._resolution_combo)
        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def result_enable_gpu(self) -> bool:
        return bool(self._gpu_switch.isChecked())

    def result_trim_ep1_continued(self) -> bool:
        return bool(self._trim_switch.isChecked())

    def result_auto_select_after_import(self) -> bool:
        return bool(self._auto_select_switch.isChecked())

    def result_resolution(self) -> str:
        data = self._resolution_combo.currentData()
        return RenderService.normalize_render_resolution(
            str(data) if data is not None else ""
        )
