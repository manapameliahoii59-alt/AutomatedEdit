import os

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QRadioButton,
    QSpinBox,
    QStyle,
    QStyleOptionButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid
from qfluentwidgets import (
    BodyLabel,
    Dialog,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SubtitleLabel,
    TableWidget,
    FluentIcon as FIF,
    isDarkTheme,
    qconfig,
)

from app.common.config import cfg
from app.common.export_paths import build_clip_export_filename, resolve_clip_export_root
from app.common.plan_settings import (
    DEFAULT_CLIP_COUNT,
    DEFAULT_GLOBAL_SPEED,
    DEFAULT_MAX_DURATION_SECONDS,
    DEFAULT_MIXED_CLIP_COUNT,
    DEFAULT_MIXED_MAX_DURATION_SECONDS,
    DEFAULT_SHORT_MAX_DURATION_SECONDS,
    GLOBAL_SPEED_CHOICES,
    MAX_CLIP_COUNT,
    MAX_MIXED_CLIP_COUNT,
    MIN_CLIP_COUNT,
    PLAN_MODE_LONG,
    PLAN_MODE_MIXED,
    PLAN_MODE_SHORT,
    clamp_clip_count,
    clamp_global_speed,
    clamp_max_duration_seconds,
    clamp_mixed_max_duration_seconds,
    clamp_plan_mode,
    clamp_short_max_duration_seconds,
    max_duration_minutes_from_seconds,
    max_duration_seconds_from_minutes,
    mixed_max_duration_minutes_from_seconds,
    mixed_max_duration_seconds_from_minutes,
    nearest_global_speed_choice,
    short_max_duration_minutes_from_seconds,
    short_max_duration_seconds_from_minutes,
)
from app.ui.components.clip_settings_dialog import ClipSettingsDialog
from app.ui.components.export_name_format_dialog import ExportNameFormatDialog
from app.ui.components.outro_settings_dialog import OutroSettingsDialog
from app.ui.components.overlay_text_groups_dialog import OverlayTextGroupsDialog
from app.common.runtime import is_dev_runtime
from app.common.utils import StyleSheet, setup_confirm_dialog, show_dialog, show_toast
from app.data.models.drama_project import DramaProject, DramaStatus
from app.data.services.changdu_paths import resolve_video_download_root
from app.data.services.drama_folder_service import (
    DramaFolderError,
    list_drama_folders_under,
    scan_drama_folder,
)
from app.data.services.render_service import (
    NVENC_PRESET_CHOICES,
    RESOLUTION_CHOICES,
    X264_PRESET_CHOICES,
    RenderService,
)
from app.ui.components.bar import ProgressInfoBar

from .view_model import ClipEditViewModel

STATUS_LABELS = {
    DramaStatus.PENDING: "待处理",
    DramaStatus.IN_PROGRESS: "处理中",
    DramaStatus.DONE: "已完成",
}


class _SelectAllHeader(QHeaderView):
    """首列表头绘制勾选框，点击可全选/取消全选。"""

    selectAllClicked = Signal(bool)

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self._state = Qt.CheckState.Unchecked
        self.setSectionsClickable(True)
        self.setHighlightSections(False)

    def set_select_state(self, state: Qt.CheckState) -> None:
        if self._state == state:
            return
        self._state = state
        self.viewport().update()

    def select_state(self) -> Qt.CheckState:
        return self._state

    def _checkbox_rect(self, section_rect):
        opt = QStyleOptionButton()
        style = self.style()
        size = style.subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator, opt, self
        ).size()
        if not size.isValid() or size.width() <= 0:
            size = style.sizeFromContents(
                QStyle.ContentsType.CT_CheckBox, opt, size, self
            )
        if not size.isValid() or size.width() <= 0:
            size.setWidth(16)
            size.setHeight(16)
        x = section_rect.x() + (section_rect.width() - size.width()) // 2
        y = section_rect.y() + (section_rect.height() - size.height()) // 2
        return QRect(x, y, size.width(), size.height())

    def paintSection(self, painter, rect, logicalIndex):
        painter.save()
        super().paintSection(painter, rect, logicalIndex)
        painter.restore()
        if logicalIndex != 0:
            return
        opt = QStyleOptionButton()
        opt.rect = self._checkbox_rect(rect)
        opt.state = QStyle.StateFlag.State_Enabled
        if self._state == Qt.CheckState.Checked:
            opt.state |= QStyle.StateFlag.State_On
        elif self._state == Qt.CheckState.PartiallyChecked:
            opt.state |= QStyle.StateFlag.State_NoChange
        else:
            opt.state |= QStyle.StateFlag.State_Off
        self.style().drawControl(QStyle.ControlElement.CE_CheckBox, opt, painter, self)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            idx = self.logicalIndexAt(event.position().toPoint())
            if idx == 0:
                # 半选或未选 → 全选；已全选 → 取消
                checked = self._state != Qt.CheckState.Checked
                self.set_select_state(
                    Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
                )
                self.selectAllClicked.emit(checked)
                event.accept()
                return
        super().mousePressEvent(event)


class ClipEditPage(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._parent_window = parent
        self.vm = ClipEditViewModel(self)
        self.setObjectName("clip_edit_page")
        self.loading_bar = None
        self._busy = False
        self._init_ui()
        self._bind_view_model()
        StyleSheet.CONTENT.apply(self)

    def _init_ui(self):
        self.scroll_widget = QWidget()
        self.scroll_widget.setObjectName("clipEditScrollWidget")
        self.setWidget(self.scroll_widget)
        self.setWidgetResizable(True)

        layout = QVBoxLayout(self.scroll_widget)
        layout.setContentsMargins(36, 20, 36, 20)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel("自动化剪辑", self.scroll_widget))
        header.addStretch(1)
        layout.addLayout(header)

        layout.addWidget(
            BodyLabel(
                "导入剧集后，依次执行「识别视频 → 策划 → 动态渲染」三步。",
                self.scroll_widget,
            )
        )

        export_row = QHBoxLayout()
        export_row.setSpacing(8)
        export_row.addWidget(BodyLabel("导出目录：", self.scroll_widget))
        self.export_path_label = BodyLabel(
            resolve_clip_export_root(), self.scroll_widget
        )
        self.export_path_label.setWordWrap(True)
        export_row.addWidget(self.export_path_label, 1)
        self.export_browse_btn = PushButton("浏览…", self.scroll_widget)
        self.export_browse_btn.clicked.connect(self._pick_export_dir)
        self.export_open_btn = PushButton("打开文件夹", self.scroll_widget)
        self.export_open_btn.clicked.connect(self._open_export_dir)
        export_row.addWidget(self.export_browse_btn)
        export_row.addWidget(self.export_open_btn)
        layout.addLayout(export_row)

        name_tag_row = QHBoxLayout()
        name_tag_row.setSpacing(8)
        name_tag_row.addWidget(BodyLabel("文件名标识：", self.scroll_widget))
        self.export_name_tag_input = LineEdit(self.scroll_widget)
        self.export_name_tag_input.setPlaceholderText("如：阿飞")
        self.export_name_tag_input.setMaxLength(20)
        self.export_name_tag_input.setText(
            str(cfg.clip_export_name_tag.value or "")[:20]
        )
        self.export_name_tag_input.setClearButtonEnabled(True)
        self.export_name_tag_input.setFixedWidth(140)
        self.export_name_tag_input.editingFinished.connect(self._save_export_name_tag)
        self.export_name_tag_input.textChanged.connect(self._update_export_name_preview)
        name_tag_row.addWidget(self.export_name_tag_input)
        self.export_name_format_btn = PushButton("格式", self.scroll_widget)
        self.export_name_format_btn.setToolTip("自定义文件名中的日期和序号格式")
        self.export_name_format_btn.clicked.connect(self._open_export_name_format)
        name_tag_row.addWidget(self.export_name_format_btn)
        self.export_name_preview_label = BodyLabel("", self.scroll_widget)
        self.export_name_preview_label.setWordWrap(True)
        name_tag_row.addWidget(self.export_name_preview_label, 1)
        self.import_btn = PrimaryPushButton(
            FIF.FOLDER_ADD, "导入剧目", self.scroll_widget
        )
        self.import_btn.clicked.connect(self._pick_drama_folder)
        name_tag_row.addWidget(self.import_btn)
        layout.addLayout(name_tag_row)
        self._update_export_name_preview()

        batch_row = QHBoxLayout()
        batch_row.setSpacing(8)
        self.batch_all_btn = PrimaryPushButton("一键执行", self.scroll_widget)
        self.batch_all_btn.clicked.connect(self._batch_all)
        self.batch_transcribe_btn = PushButton("批量识别", self.scroll_widget)
        self.batch_transcribe_btn.clicked.connect(self._batch_transcribe)
        self.batch_plan_btn = PushButton("批量策划", self.scroll_widget)
        self.batch_plan_btn.clicked.connect(self._batch_plan)
        self.batch_render_btn = PushButton("批量渲染", self.scroll_widget)
        self.batch_render_btn.clicked.connect(self._batch_render)
        batch_row.addWidget(self.batch_all_btn)
        batch_row.addWidget(self.batch_transcribe_btn)
        batch_row.addWidget(self.batch_plan_btn)
        batch_row.addWidget(self.batch_render_btn)
        self.encode_settings_btn = None
        if is_dev_runtime():
            self.encode_settings_btn = PushButton(
                FIF.SETTING, "编码设置", self.scroll_widget
            )
            self.encode_settings_btn.setToolTip(
                "设置 GPU / CPU 编码档位（默认 p5 / superfast，可选更快档位）"
            )
            self.encode_settings_btn.clicked.connect(self._open_encode_settings)
        self.plan_settings_btn = PushButton(
            FIF.EDIT, "策划设置", self.scroll_widget
        )
        self.plan_settings_btn.setToolTip(
            "选择短片/长片模式、条数、最长时长，以及成片倍速"
        )
        self.plan_settings_btn.clicked.connect(self._open_plan_settings)
        self.overlay_text_btn = PushButton(
            FIF.FONT, "画面文字", self.scroll_widget
        )
        self.overlay_text_btn.setToolTip(
            "自定义渲染画面上的剧名与提示文字（字体、颜色、位置等）"
        )
        self.overlay_text_btn.clicked.connect(self._open_overlay_text_settings)
        self.outro_btn = PushButton(FIF.VIDEO, "片尾设置", self.scroll_widget)
        self.outro_btn.setToolTip(
            "上传多个横屏/竖屏片尾，勾选启用；未勾选自定义时用内置默认"
        )
        self.outro_btn.clicked.connect(self._open_outro_settings)
        self.clip_settings_btn = PushButton(
            FIF.SETTING, "设置", self.scroll_widget
        )
        self.clip_settings_btn.setToolTip("去掉未完待续等剪辑选项")
        self.clip_settings_btn.clicked.connect(self._open_clip_settings)
        if self.encode_settings_btn is not None:
            batch_row.addWidget(self.encode_settings_btn)
        batch_row.addWidget(self.plan_settings_btn)
        batch_row.addWidget(self.overlay_text_btn)
        batch_row.addWidget(self.outro_btn)
        batch_row.addWidget(self.clip_settings_btn)
        batch_row.addStretch(1)
        layout.addLayout(batch_row)

        self.table = TableWidget(self.scroll_widget)
        self.table.setColumnCount(7)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(TableWidget.SelectionMode.SingleSelection)
        self._select_all_header = _SelectAllHeader(
            Qt.Orientation.Horizontal, self.table
        )
        self.table.setHorizontalHeader(self._select_all_header)
        self.table.setHorizontalHeaderLabels(
            ["", "剧名", "集数", "识别", "策划", "渲染", "操作"]
        )
        table_header = self._select_all_header
        table_header.setToolTip("全选")
        # 仅首列点击用于全选；避免误触其它列表头
        table_header.setSectionsClickable(True)
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 44)
        self.table.setColumnWidth(1, 180)
        self.table.setColumnWidth(2, 72)
        self.table.setColumnWidth(3, 96)
        self.table.setColumnWidth(4, 180)
        self.table.setColumnWidth(5, 180)
        self.table.setColumnWidth(6, 280)
        self._select_all_header.selectAllClicked.connect(self._set_all_rows_checked)
        self.table.itemChanged.connect(self._on_table_item_changed)
        layout.addWidget(self.table, 1)

        self.setViewportMargins(0, 0, 0, 0)

    def _bind_view_model(self):
        self.vm.projectsChanged.connect(self._refresh_table)
        self.vm.loadingChanged.connect(self._handle_loading)
        self.vm.loadingContentChanged.connect(self._handle_loading_content)
        self.vm.stageProgressChanged.connect(self._on_stage_progress)
        self.vm.messageReceived.connect(lambda msg: show_toast(self, msg))
        self.vm.errorOccurred.connect(lambda msg: show_dialog(self, msg, "提示"))
        self.vm.settingsLoaded.connect(self._on_settings_loaded)
        self._refresh_table(self.vm.get_projects())
        qconfig.themeChanged.connect(lambda *_: self._refresh_table(self.vm.get_projects()))

    def _on_settings_loaded(self, _clip_edit: dict):
        tag = str(cfg.clip_export_name_tag.value or "")[:20]
        if self.export_name_tag_input.text() != tag:
            self.export_name_tag_input.blockSignals(True)
            self.export_name_tag_input.setText(tag)
            self.export_name_tag_input.blockSignals(False)
        self._update_export_name_preview()

    def _refresh_table(self, projects: list[DramaProject]):
        checked_ids = set(self._get_checked_ids())
        self.table.blockSignals(True)
        self.table.setRowCount(len(projects))
        for row, project in enumerate(projects):
            st = self.vm._status.get(project.id, {})

            check_item = QTableWidgetItem()
            check_item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            if project.id in checked_ids:
                check_item.setCheckState(Qt.CheckState.Checked)
            else:
                check_item.setCheckState(Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, check_item)

            name_item = QTableWidgetItem(project.name)
            name_item.setToolTip(project.name)
            self.table.setItem(row, 1, name_item)
            count_item = QTableWidgetItem(str(project.episode_count))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 2, count_item)

            for col, key in [(3, "transcribe"), (4, "plan"), (5, "render")]:
                s = st.get(key, DramaStatus.PENDING)
                progress = self.vm.get_stage_progress(project.id, key)
                if s == DramaStatus.IN_PROGRESS and progress:
                    label = progress
                else:
                    label = STATUS_LABELS.get(s, "待处理")
                item = QTableWidgetItem(label)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setToolTip(label)
                if s == DramaStatus.DONE:
                    item.setForeground(
                        QColor("#3dd68c") if isDarkTheme() else Qt.GlobalColor.darkGreen
                    )
                elif s == DramaStatus.IN_PROGRESS:
                    item.setForeground(
                        QColor("#f2c14e") if isDarkTheme() else Qt.GlobalColor.darkYellow
                    )
                self.table.setItem(row, col, item)

            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(4, 0, 4, 0)
            cell_layout.setSpacing(4)

            transcribe_btn = PushButton("识别", cell)
            transcribe_btn.setFixedWidth(56)
            transcribe_btn.setProperty("project_id", project.id)
            transcribe_btn.clicked.connect(
                lambda _=False, pid=project.id: self.vm.start_transcribe(pid)
            )

            plan_btn = PushButton("策划", cell)
            plan_btn.setFixedWidth(56)
            plan_btn.setProperty("project_id", project.id)
            plan_btn.clicked.connect(
                lambda _=False, pid=project.id: self.vm.start_planning(pid)
            )

            render_btn = PushButton("渲染", cell)
            render_btn.setFixedWidth(56)
            render_btn.setProperty("project_id", project.id)
            render_btn.clicked.connect(
                lambda _=False, pid=project.id: self.vm.start_render(pid)
            )

            del_btn = PushButton("删除", cell)
            del_btn.setFixedWidth(56)
            del_btn.setProperty("project_id", project.id)
            del_btn.clicked.connect(
                lambda _=False, pid=project.id: self._confirm_delete(pid)
            )

            for btn in (transcribe_btn, plan_btn, render_btn, del_btn):
                btn.setEnabled(not self._busy)

            cell_layout.addWidget(transcribe_btn)
            cell_layout.addWidget(plan_btn)
            cell_layout.addWidget(render_btn)
            cell_layout.addWidget(del_btn)
            self.table.setCellWidget(row, 6, cell)

        self.table.blockSignals(False)
        self._sync_select_all_checkbox()
        self._update_export_name_preview()

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        if item is None or item.column() != 0:
            return
        self._sync_select_all_checkbox()

    def _sync_select_all_checkbox(self) -> None:
        header = getattr(self, "_select_all_header", None)
        if header is None or not isValid(header):
            return
        n = self.table.rowCount()
        checked = 0
        for row in range(n):
            item = self.table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                checked += 1
        if n == 0 or checked == 0:
            header.set_select_state(Qt.CheckState.Unchecked)
        elif checked == n:
            header.set_select_state(Qt.CheckState.Checked)
        else:
            header.set_select_state(Qt.CheckState.PartiallyChecked)

    def _preview_project_name(self) -> str:
        projects = self.vm.get_projects()
        return projects[0].name if projects else "剧名示例"

    def _update_export_name_preview(self, _text: str = "") -> None:
        tag = self.export_name_tag_input.text().strip()
        filename = build_clip_export_filename(
            self._preview_project_name(),
            1,
            tag=tag,
        )
        self.export_name_preview_label.setText(f"效果：{filename}.mp4")

    def _get_checked_ids(self) -> list[str]:
        projects = self.vm.get_projects()
        ids = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                if row < len(projects):
                    ids.append(projects[row].id)
        return ids

    def _set_all_rows_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(state)
        self.table.blockSignals(False)
        self._sync_select_all_checkbox()

    def _batch_transcribe(self):
        ids = self._get_checked_ids()
        if not ids:
            show_dialog(self, "请先勾选要处理的剧目", "提示")
            return
        self.vm.batch_transcribe(ids)

    def _batch_plan(self):
        ids = self._get_checked_ids()
        if not ids:
            show_dialog(self, "请先勾选要处理的剧目", "提示")
            return
        self.vm.batch_plan(ids)

    def _batch_render(self):
        ids = self._get_checked_ids()
        if not ids:
            show_dialog(self, "请先勾选要处理的剧目", "提示")
            return
        self.vm.batch_render(ids)

    def _open_encode_settings(self):
        dlg = QDialog(self.window())
        dlg.setWindowTitle("编码设置")
        dlg.setMinimumWidth(420)
        layout = QVBoxLayout(dlg)

        tip = QLabel(
            "档位越快通常画质略降。默认：GPU p5、CPU superfast。\n"
            "更改后新渲染会按新档位重建缓存；旧缓存不会自动删除。",
            dlg,
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        form = QFormLayout()
        gpu_combo = QComboBox(dlg)
        for value, label in NVENC_PRESET_CHOICES:
            gpu_combo.addItem(label, value)
        cur_gpu = RenderService.normalize_nvenc_preset(
            str(cfg.encode_nvenc_preset.value)
        )
        gpu_idx = gpu_combo.findData(cur_gpu)
        if gpu_idx >= 0:
            gpu_combo.setCurrentIndex(gpu_idx)

        cpu_combo = QComboBox(dlg)
        for value, label in X264_PRESET_CHOICES:
            cpu_combo.addItem(label, value)
        cur_cpu = RenderService.normalize_x264_preset(
            str(cfg.encode_x264_preset.value)
        )
        cpu_idx = cpu_combo.findData(cur_cpu)
        if cpu_idx >= 0:
            cpu_combo.setCurrentIndex(cpu_idx)

        form.addRow("GPU 编码档位 (NVENC)：", gpu_combo)
        form.addRow("CPU 编码档位 (libx264)：", cpu_combo)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dlg,
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        qconfig.set(cfg.encode_nvenc_preset, str(gpu_combo.currentData()))
        qconfig.set(cfg.encode_x264_preset, str(cpu_combo.currentData()))
        show_toast(
            self,
            f"已保存：GPU {gpu_combo.currentData()} / CPU {cpu_combo.currentData()}",
            title="编码设置",
        )

    def _open_plan_settings(self):
        dlg = QDialog(self.window())
        dlg.setWindowTitle("策划设置")
        dlg.setMinimumWidth(520)
        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)

        mode_row = QHBoxLayout()
        short_radio = QRadioButton("短片模式", dlg)
        long_radio = QRadioButton("长片模式", dlg)
        mixed_radio = QRadioButton("混合模式", dlg)
        mode_group = QButtonGroup(dlg)
        mode_group.addButton(short_radio)
        mode_group.addButton(long_radio)
        mode_group.addButton(mixed_radio)
        initial_mode = clamp_plan_mode(cfg.plan_mode.value)
        if initial_mode == PLAN_MODE_SHORT:
            short_radio.setChecked(True)
        elif initial_mode == PLAN_MODE_MIXED:
            mixed_radio.setChecked(True)
        else:
            long_radio.setChecked(True)
        mode_row.addWidget(short_radio)
        mode_row.addWidget(long_radio)
        mode_row.addWidget(mixed_radio)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        tip = BodyLabel(dlg)
        tip.setWordWrap(True)
        layout.addWidget(tip)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        count_combo = QComboBox(dlg)
        count_combo.setMinimumWidth(200)

        max_combo = QComboBox(dlg)
        max_combo.setMinimumWidth(200)

        speed_combo = QComboBox(dlg)
        speed_combo.setMinimumWidth(200)
        for spd in GLOBAL_SPEED_CHOICES:
            label = "原速（不加速）" if abs(spd - 1.0) < 1e-6 else f"{spd:.1f} 倍"
            if abs(spd - DEFAULT_GLOBAL_SPEED) < 1e-6:
                label += "（默认）"
            speed_combo.addItem(label, spd)

        form.addRow("总条数", count_combo)
        form.addRow("最长时长", max_combo)
        form.addRow("成片倍速", speed_combo)
        layout.addLayout(form)

        values = {
            PLAN_MODE_SHORT: {
                "count": clamp_clip_count(cfg.plan_short_clip_count.value),
                "max_min": short_max_duration_minutes_from_seconds(
                    clamp_short_max_duration_seconds(
                        cfg.plan_short_max_duration_sec.value
                    )
                ),
            },
            PLAN_MODE_LONG: {
                "count": clamp_clip_count(cfg.plan_clip_count.value),
                "max_min": max_duration_minutes_from_seconds(
                    clamp_max_duration_seconds(cfg.plan_max_duration_sec.value)
                ),
            },
            PLAN_MODE_MIXED: {
                "count": clamp_clip_count(
                    cfg.plan_mixed_clip_count.value, max_count=MAX_MIXED_CLIP_COUNT
                ),
                "max_min": mixed_max_duration_minutes_from_seconds(
                    clamp_mixed_max_duration_seconds(
                        cfg.plan_mixed_max_duration_sec.value
                    )
                ),
            },
        }
        current_mode = {"value": initial_mode}
        initial_speed = clamp_global_speed(cfg.plan_global_speed.value)

        def _set_combo_value(combo: QComboBox, value) -> None:
            idx = combo.findData(value)
            if idx < 0:
                for i in range(combo.count()):
                    data = combo.itemData(i)
                    try:
                        if abs(float(data) - float(value)) < 1e-6:
                            idx = i
                            break
                    except (TypeError, ValueError):
                        continue
            combo.setCurrentIndex(idx if idx >= 0 else 0)

        def _combo_int(combo: QComboBox) -> int:
            data = combo.currentData()
            return int(data) if data is not None else MIN_CLIP_COUNT

        def _combo_speed(combo: QComboBox) -> float:
            data = combo.currentData()
            return clamp_global_speed(data if data is not None else DEFAULT_GLOBAL_SPEED)

        def _refill_count_combo(mode: str) -> None:
            count_combo.blockSignals(True)
            count_combo.clear()
            hi = MAX_MIXED_CLIP_COUNT if mode == PLAN_MODE_MIXED else MAX_CLIP_COUNT
            for n in range(MIN_CLIP_COUNT, hi + 1):
                count_combo.addItem(f"{n} 条", n)
            count_combo.blockSignals(False)

        def _refill_max_combo(mode: str) -> None:
            max_combo.blockSignals(True)
            max_combo.clear()
            if mode == PLAN_MODE_SHORT:
                for m in range(2, 7):
                    max_combo.addItem(f"{m} 分钟", m)
            elif mode == PLAN_MODE_MIXED:
                for m in range(6, 16):
                    max_combo.addItem(f"{m} 分钟", m)
            else:
                for m in range(5, 16):
                    max_combo.addItem(f"{m} 分钟", m)
            max_combo.blockSignals(False)

        def _active_mode() -> str:
            if short_radio.isChecked():
                return PLAN_MODE_SHORT
            if mixed_radio.isChecked():
                return PLAN_MODE_MIXED
            return PLAN_MODE_LONG

        def _persist_current():
            mode = current_mode["value"]
            values[mode]["count"] = _combo_int(count_combo)
            values[mode]["max_min"] = _combo_int(max_combo)

        def _apply_mode(mode: str):
            current_mode["value"] = mode
            if mode == PLAN_MODE_SHORT:
                tip.setText(
                    "短片：最短固定 2 分钟；最长可选 2～6 分钟（默认 5）。\n"
                    "不分 A/B 组。成片倍速三种模式共用；大于 1 会加速成片。"
                    "条数与时长为策划目标，实际产出可能略有浮动。"
                )
            elif mode == PLAN_MODE_MIXED:
                tip.setText(
                    "混合：最短固定 2 分钟；最长可选 6～15 分钟（默认 12）。\n"
                    "按 A/B 组策划，条数最高 20。成片倍速三种模式共用；"
                    "条数与时长为策划目标，实际产出可能略有浮动。"
                )
            else:
                tip.setText(
                    "长片：最短固定 2.5 分钟；最长可选 5～15 分钟（默认 12）。\n"
                    "按 A/B 组策划。成片倍速三种模式共用；大于 1 会加速成片。"
                    "条数与时长为策划目标，实际产出可能略有浮动。"
                )
            _refill_count_combo(mode)
            _refill_max_combo(mode)
            _set_combo_value(count_combo, values[mode]["count"])
            _set_combo_value(max_combo, values[mode]["max_min"])

        def _on_mode_toggled(_checked=False):
            if not (
                short_radio.isChecked()
                or long_radio.isChecked()
                or mixed_radio.isChecked()
            ):
                return
            new_mode = _active_mode()
            if new_mode == current_mode["value"]:
                return
            _persist_current()
            _apply_mode(new_mode)

        short_radio.toggled.connect(_on_mode_toggled)
        long_radio.toggled.connect(_on_mode_toggled)
        mixed_radio.toggled.connect(_on_mode_toggled)
        _apply_mode(initial_mode)
        _set_combo_value(speed_combo, nearest_global_speed_choice(initial_speed))

        btn_row = QHBoxLayout()
        reset_btn = PushButton("重置默认", dlg)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dlg,
        )
        btn_row.addWidget(reset_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(buttons)
        layout.addLayout(btn_row)

        def _reset():
            mode = _active_mode()
            if mode == PLAN_MODE_SHORT:
                values[mode]["count"] = DEFAULT_CLIP_COUNT
                values[mode]["max_min"] = short_max_duration_minutes_from_seconds(
                    DEFAULT_SHORT_MAX_DURATION_SECONDS
                )
            elif mode == PLAN_MODE_MIXED:
                values[mode]["count"] = DEFAULT_MIXED_CLIP_COUNT
                values[mode]["max_min"] = mixed_max_duration_minutes_from_seconds(
                    DEFAULT_MIXED_MAX_DURATION_SECONDS
                )
            else:
                values[mode]["count"] = DEFAULT_CLIP_COUNT
                values[mode]["max_min"] = max_duration_minutes_from_seconds(
                    DEFAULT_MAX_DURATION_SECONDS
                )
            _set_combo_value(count_combo, values[mode]["count"])
            _set_combo_value(max_combo, values[mode]["max_min"])
            _set_combo_value(speed_combo, DEFAULT_GLOBAL_SPEED)

        reset_btn.clicked.connect(_reset)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        _persist_current()
        mode = _active_mode()
        global_speed = _combo_speed(speed_combo)
        short_count = clamp_clip_count(values[PLAN_MODE_SHORT]["count"])
        short_max_sec = short_max_duration_seconds_from_minutes(
            values[PLAN_MODE_SHORT]["max_min"]
        )
        long_count = clamp_clip_count(values[PLAN_MODE_LONG]["count"])
        long_max_sec = max_duration_seconds_from_minutes(
            values[PLAN_MODE_LONG]["max_min"]
        )
        mixed_count = clamp_clip_count(
            values[PLAN_MODE_MIXED]["count"], max_count=MAX_MIXED_CLIP_COUNT
        )
        mixed_max_sec = mixed_max_duration_seconds_from_minutes(
            values[PLAN_MODE_MIXED]["max_min"]
        )

        qconfig.set(cfg.plan_mode, mode)
        qconfig.set(cfg.plan_short_clip_count, short_count)
        qconfig.set(cfg.plan_short_max_duration_sec, short_max_sec)
        qconfig.set(cfg.plan_clip_count, long_count)
        qconfig.set(cfg.plan_max_duration_sec, long_max_sec)
        qconfig.set(cfg.plan_mixed_clip_count, mixed_count)
        qconfig.set(cfg.plan_mixed_max_duration_sec, mixed_max_sec)
        qconfig.set(cfg.plan_global_speed, global_speed)
        self.vm.save_plan_settings(
            mode=mode,
            clip_count=long_count,
            max_duration_sec=long_max_sec,
            short_clip_count=short_count,
            short_max_duration_sec=short_max_sec,
            mixed_clip_count=mixed_count,
            mixed_max_duration_sec=mixed_max_sec,
            global_speed=global_speed,
        )
        if mode == PLAN_MODE_SHORT:
            active_count = short_count
            active_max_min = values[PLAN_MODE_SHORT]["max_min"]
            mode_label = "短片"
        elif mode == PLAN_MODE_MIXED:
            active_count = mixed_count
            active_max_min = values[PLAN_MODE_MIXED]["max_min"]
            mode_label = "混合"
        else:
            active_count = long_count
            active_max_min = values[PLAN_MODE_LONG]["max_min"]
            mode_label = "长片"
        speed_label = (
            "原速" if abs(global_speed - 1.0) < 1e-6 else f"{global_speed:.1f}x"
        )
        show_toast(
            self,
            f"已保存：{mode_label}模式，{active_count} 条，最长 {active_max_min} 分钟，{speed_label}",
            title="策划设置",
        )

    def _open_overlay_text_settings(self):
        dlg = OverlayTextGroupsDialog(
            self.window(),
            project_name=self._preview_project_name(),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        lib = dlg.result_library()
        self.vm.save_overlay_text_library(lib)
        if lib.get("no_text"):
            show_toast(self, "已关闭画面文字", title="画面文字")
        else:
            show_toast(self, "画面文字组已保存", title="画面文字")

    def _open_clip_settings(self):
        dlg = ClipSettingsDialog(self.window())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        enabled = dlg.result_trim_ep1_continued()
        qconfig.set(cfg.clip_trim_ep1_continued, enabled)
        resolution = dlg.result_resolution()
        qconfig.set(cfg.encode_output_resolution, resolution)
        self.vm.save_output_resolution(resolution)
        resolution_label = dict(RESOLUTION_CHOICES).get(resolution, resolution)
        show_toast(
            self,
            f"去掉未完待续：{'开' if enabled else '关'} · 成片分辨率：{resolution_label}",
            title="设置",
        )

    def _open_outro_settings(self):
        dlg = OutroSettingsDialog(self.window())
        dlg.exec()

    def _batch_all(self):
        if not self.vm.get_projects():
            show_dialog(self, "暂未导入任何剧目", "提示")
            return

        ids = self._get_checked_ids()
        auto_select_all = not ids
        if auto_select_all:
            ids = [p.id for p in self.vm.get_projects()]

        w = Dialog(
            "一键执行",
            f"确认对{'全部' if auto_select_all else '选中的'} {len(ids)} 个剧目执行「识别视频 → 方案策划 → 动态渲染」完整流程吗？",
            self.window(),
        )
        setup_confirm_dialog(w, window_title="一键执行")
        w.setFixedWidth(440)
        if w.exec():
            try:
                if auto_select_all:
                    self._set_all_rows_checked(True)
                self.vm.batch_all(ids)
            except Exception as e:
                show_dialog(self, f"一键执行失败：{e}", "错误")

    def _confirm_delete(self, project_id: str):
        project = next((p for p in self.vm.get_projects() if p.id == project_id), None)
        if not project:
            return
        w = Dialog("删除剧目", f"确定要删除《{project.name}》吗？", self.window())
        setup_confirm_dialog(w, window_title="删除剧目")
        if w.exec():
            self.vm.remove_project(project_id)

    def _save_export_name_tag(self):
        tag = self.export_name_tag_input.text().strip()[:20]
        if self.export_name_tag_input.text() != tag:
            self.export_name_tag_input.blockSignals(True)
            self.export_name_tag_input.setText(tag)
            self.export_name_tag_input.blockSignals(False)
        qconfig.set(cfg.clip_export_name_tag, tag)
        self._update_export_name_preview()
        self.vm.save_export_name_tag(tag)

    def _open_export_name_format(self):
        dlg = ExportNameFormatDialog(
            self.window(),
            project_name=self._preview_project_name(),
            tag=self.export_name_tag_input.text().strip(),
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        date_fmt = dlg.result_date_format()
        seq_fmt = dlg.result_seq_format()
        qconfig.set(cfg.clip_export_date_format, date_fmt)
        qconfig.set(cfg.clip_export_seq_format, seq_fmt)
        self._update_export_name_preview()
        self.vm.save_export_name_format(date_fmt, seq_fmt)
        show_toast(self, "文件名格式已保存", title="文件名格式")

    def _pick_export_dir(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择导出总目录",
            resolve_clip_export_root(),
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )
        if folder:
            qconfig.set(cfg.clip_export_dir, folder)
            self.export_path_label.setText(folder)

    def _open_export_dir(self):
        path = resolve_clip_export_root()
        os.makedirs(path, exist_ok=True)
        os.startfile(path)

    def _pick_drama_folder(self):
        start = (cfg.clip_last_import_dir.value or "").strip()
        if not start or not os.path.isdir(start):
            start = resolve_video_download_root()
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择剧集文件夹（可直接选含多部剧的总目录）",
            start,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )
        if not folder:
            return
        # 记住上一级目录，下次可直接挑选同目录下的其他剧
        parent = os.path.dirname(folder.rstrip("\\/"))
        remember = parent if parent and os.path.isdir(parent) else folder
        qconfig.set(cfg.clip_last_import_dir, remember)

        # 文件夹直接含视频 → 单剧导入（原有行为）
        try:
            scan_drama_folder(folder)
        except DramaFolderError:
            # 不含视频 → 视为剧目总目录，扫描子文件夹批量导入
            folders = list_drama_folders_under(folder)
            if not folders:
                show_dialog(
                    self,
                    "该文件夹内未找到视频，其子文件夹中也没有可导入的剧目"
                    "（剧目文件夹需直接包含 mp4 等视频文件）",
                    "提示",
                )
                return
            self.vm.import_drama_folders(folders)
            return
        self.vm.import_drama_folder(folder)

    def _handle_loading_content(self, content: str):
        if self.loading_bar is not None and isValid(self.loading_bar):
            self.loading_bar.contentLabel.setText(content)

    def _on_stage_progress(self, project_id: str, step: str, text: str):
        step_col = {"transcribe": 3, "plan": 4, "render": 5}.get(step)
        if step_col is None:
            return
        projects = self.vm.get_projects()
        for row, project in enumerate(projects):
            if project.id != project_id:
                continue
            item = self.table.item(row, step_col)
            if item is None:
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, step_col, item)
            else:
                item.setText(text)
            item.setToolTip(text)
            item.setForeground(
                QColor("#f2c14e") if isDarkTheme() else Qt.GlobalColor.darkYellow
            )
            break

    def _handle_loading(self, loading: bool, title: str, content: str):
        self._busy = loading
        widgets = [
            self.export_browse_btn,
            self.export_open_btn,
            self.export_name_tag_input,
            self.export_name_format_btn,
            self.batch_all_btn,
            self.batch_transcribe_btn,
            self.batch_plan_btn,
            self.batch_render_btn,
            self.import_btn,
            self.plan_settings_btn,
            self.overlay_text_btn,
            self.outro_btn,
            self.clip_settings_btn,
            self.table,
        ]
        if self.encode_settings_btn is not None:
            widgets.append(self.encode_settings_btn)
        for w in widgets:
            w.setEnabled(not loading)
        if loading:
            if self.loading_bar is None or not isValid(self.loading_bar):
                self.loading_bar = ProgressInfoBar(title, content, self)
                self.loading_bar.cancelled.connect(self._on_progress_cancelled)
                self.loading_bar.show()
            else:
                self.loading_bar.titleLabel.setText(title)
                self.loading_bar.contentLabel.setText(content)
        else:
            self._close_loading()
            self._refresh_table(self.vm.get_projects())

    def _on_progress_cancelled(self):
        self.loading_bar = None
        self.vm.request_cancel()

    def _close_loading(self):
        if self.loading_bar and isValid(self.loading_bar):
            self.loading_bar.hide()
        self.loading_bar = None
