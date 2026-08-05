import os

from PySide6.QtCore import Qt
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
    DEFAULT_MAX_DURATION_SECONDS,
    DEFAULT_SHORT_MAX_DURATION_SECONDS,
    MAX_CLIP_COUNT,
    MIN_CLIP_COUNT,
    PLAN_MODE_LONG,
    PLAN_MODE_SHORT,
    clamp_clip_count,
    clamp_max_duration_seconds,
    clamp_plan_mode,
    clamp_short_max_duration_seconds,
    max_duration_minutes_from_seconds,
    max_duration_seconds_from_minutes,
    short_max_duration_minutes_from_seconds,
    short_max_duration_seconds_from_minutes,
)
from app.common.overlay_text_settings import (
    FONT_CHOICES,
    default_overlay_disclaimer,
    default_overlay_title,
    load_overlay_disclaimer_from_cfg,
    load_overlay_title_from_cfg,
    position_for_orientation,
    save_overlay_styles_to_cfg,
    set_position_for_orientation,
)
from app.ui.components.overlay_text_preview import OverlayTextPreview
from app.common.runtime import is_dev_runtime
from app.common.utils import StyleSheet, setup_confirm_dialog, show_dialog, show_toast
from app.data.models.drama_project import DramaProject, DramaStatus
from app.data.services.changdu_paths import resolve_video_download_root
from app.data.services.render_service import (
    NVENC_PRESET_CHOICES,
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
        self.export_name_tag_input.setText(cfg.clip_export_name_tag.value)
        self.export_name_tag_input.setClearButtonEnabled(True)
        self.export_name_tag_input.setFixedWidth(140)
        self.export_name_tag_input.editingFinished.connect(self._save_export_name_tag)
        self.export_name_tag_input.textChanged.connect(self._update_export_name_preview)
        name_tag_row.addWidget(self.export_name_tag_input)
        self.export_name_preview_label = BodyLabel("", self.scroll_widget)
        self.export_name_preview_label.setWordWrap(True)
        name_tag_row.addWidget(self.export_name_preview_label, 1)
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
        self.import_btn = PrimaryPushButton(
            FIF.FOLDER_ADD, "导入剧目", self.scroll_widget
        )
        self.import_btn.clicked.connect(self._pick_drama_folder)
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
            "选择短片/长片模式，并设置条数（5~15）与对应最长时长"
        )
        self.plan_settings_btn.clicked.connect(self._open_plan_settings)
        self.overlay_text_btn = PushButton(
            FIF.FONT, "画面文字", self.scroll_widget
        )
        self.overlay_text_btn.setToolTip(
            "自定义渲染画面上的剧名与提示文字（字体、颜色、位置等）"
        )
        self.overlay_text_btn.clicked.connect(self._open_overlay_text_settings)
        batch_row.addWidget(self.import_btn)
        if self.encode_settings_btn is not None:
            batch_row.addWidget(self.encode_settings_btn)
        batch_row.addWidget(self.plan_settings_btn)
        batch_row.addWidget(self.overlay_text_btn)
        batch_row.addStretch(1)
        layout.addLayout(batch_row)

        self.table = TableWidget(self.scroll_widget)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["", "剧名", "集数", "识别", "策划", "渲染", "操作"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(TableWidget.SelectionMode.SingleSelection)
        table_header = self.table.horizontalHeader()
        table_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        table_header.setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 40)
        self.table.setColumnWidth(1, 180)
        self.table.setColumnWidth(2, 72)
        self.table.setColumnWidth(3, 96)
        self.table.setColumnWidth(4, 180)
        self.table.setColumnWidth(5, 180)
        self.table.setColumnWidth(6, 280)
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
        tag = cfg.clip_export_name_tag.value
        if self.export_name_tag_input.text() != tag:
            self.export_name_tag_input.blockSignals(True)
            self.export_name_tag_input.setText(tag)
            self.export_name_tag_input.blockSignals(False)
            self._update_export_name_preview()

    def _refresh_table(self, projects: list[DramaProject]):
        checked_ids = set(self._get_checked_ids())
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

        self._update_export_name_preview()

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
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item:
                item.setCheckState(state)

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
        dlg.setMinimumWidth(440)
        layout = QVBoxLayout(dlg)

        mode_row = QHBoxLayout()
        short_radio = QRadioButton("短片模式", dlg)
        long_radio = QRadioButton("长片模式", dlg)
        mode_group = QButtonGroup(dlg)
        mode_group.addButton(short_radio)
        mode_group.addButton(long_radio)
        initial_mode = clamp_plan_mode(cfg.plan_mode.value)
        if initial_mode == PLAN_MODE_SHORT:
            short_radio.setChecked(True)
        else:
            long_radio.setChecked(True)
        mode_row.addWidget(short_radio)
        mode_row.addWidget(long_radio)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        tip = QLabel(dlg)
        tip.setWordWrap(True)
        layout.addWidget(tip)

        form = QFormLayout()
        count_spin = QSpinBox(dlg)
        count_spin.setRange(MIN_CLIP_COUNT, MAX_CLIP_COUNT)
        count_spin.setSuffix(" 条")
        max_spin = QSpinBox(dlg)
        max_spin.setSuffix(" 分钟")
        form.addRow("总条数：", count_spin)
        form.addRow("最长时长：", max_spin)
        layout.addLayout(form)

        # 两套参数各自缓存，切换模式时互不覆盖
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
        }
        current_mode = {"value": initial_mode}

        def _active_mode() -> str:
            return PLAN_MODE_SHORT if short_radio.isChecked() else PLAN_MODE_LONG

        def _persist_current_spins():
            mode = current_mode["value"]
            values[mode]["count"] = count_spin.value()
            values[mode]["max_min"] = max_spin.value()

        def _apply_mode(mode: str):
            current_mode["value"] = mode
            if mode == PLAN_MODE_SHORT:
                tip.setText(
                    "短片模式：单条最短时长固定 2 分钟。\n"
                    "「最长时长」可在 2～5 分钟之间选择，默认 5 分钟。\n\n"
                    "说明：此处设置的是目标条数与时长范围，实际产出不一定严格等于设定值，"
                    "可能因剧本内容、切点匹配等略有波动（条数可能偏少，单条时长在范围内浮动）。"
                )
                max_spin.setRange(2, 5)
            else:
                tip.setText(
                    "长片模式：单条最短时长固定 2.5 分钟。\n"
                    "「最长时长」可在 5～15 分钟之间选择，默认 12 分钟。\n\n"
                    "说明：此处设置的是目标条数与时长范围，实际产出不一定严格等于设定值，"
                    "可能因剧本内容、切点匹配等略有波动（条数可能偏少，单条时长在范围内浮动）。"
                )
                max_spin.setRange(5, 15)
            count_spin.setValue(values[mode]["count"])
            max_spin.setValue(values[mode]["max_min"])

        def _on_mode_toggled(_checked=False):
            if not short_radio.isChecked() and not long_radio.isChecked():
                return
            new_mode = _active_mode()
            if new_mode == current_mode["value"]:
                return
            _persist_current_spins()
            _apply_mode(new_mode)

        short_radio.toggled.connect(_on_mode_toggled)
        long_radio.toggled.connect(_on_mode_toggled)
        _apply_mode(initial_mode)

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
                count_spin.setValue(DEFAULT_CLIP_COUNT)
                max_spin.setValue(
                    short_max_duration_minutes_from_seconds(
                        DEFAULT_SHORT_MAX_DURATION_SECONDS
                    )
                )
            else:
                count_spin.setValue(DEFAULT_CLIP_COUNT)
                max_spin.setValue(
                    max_duration_minutes_from_seconds(DEFAULT_MAX_DURATION_SECONDS)
                )
            _persist_current_spins()

        reset_btn.clicked.connect(_reset)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        _persist_current_spins()
        mode = _active_mode()
        short_count = clamp_clip_count(values[PLAN_MODE_SHORT]["count"])
        short_max_sec = short_max_duration_seconds_from_minutes(
            values[PLAN_MODE_SHORT]["max_min"]
        )
        long_count = clamp_clip_count(values[PLAN_MODE_LONG]["count"])
        long_max_sec = max_duration_seconds_from_minutes(
            values[PLAN_MODE_LONG]["max_min"]
        )

        qconfig.set(cfg.plan_mode, mode)
        qconfig.set(cfg.plan_short_clip_count, short_count)
        qconfig.set(cfg.plan_short_max_duration_sec, short_max_sec)
        qconfig.set(cfg.plan_clip_count, long_count)
        qconfig.set(cfg.plan_max_duration_sec, long_max_sec)
        self.vm.save_plan_settings(
            mode=mode,
            clip_count=long_count,
            max_duration_sec=long_max_sec,
            short_clip_count=short_count,
            short_max_duration_sec=short_max_sec,
        )
        active_count = short_count if mode == PLAN_MODE_SHORT else long_count
        active_max_min = (
            values[PLAN_MODE_SHORT]["max_min"]
            if mode == PLAN_MODE_SHORT
            else values[PLAN_MODE_LONG]["max_min"]
        )
        mode_label = "短片" if mode == PLAN_MODE_SHORT else "长片"
        show_toast(
            self,
            f"已保存：{mode_label}模式，{active_count} 条，最长 {active_max_min} 分钟",
            title="策划设置",
        )

    def _open_overlay_text_settings(self):
        dlg = QDialog(self.window())
        dlg.setWindowTitle("画面文字")
        dlg.setMinimumSize(900, 560)
        root = QHBoxLayout(dlg)
        root.setSpacing(12)

        # ---- 左侧预览 ----
        preview = OverlayTextPreview(dlg)
        preview.set_project_name(self._preview_project_name())
        preview.setMinimumWidth(360)
        root.addWidget(preview, 3)

        # ---- 右侧参数 ----
        right = QVBoxLayout()
        tip = QLabel(
            "左侧可拖动文字设置位置。剧名模板可用 {name}；文案为空则不烧录。\n"
            "排布可选横向或竖向。横屏/竖屏各自保存一套位置，渲染时按成片方向自动选用。",
            dlg,
        )
        tip.setWordWrap(True)
        right.addWidget(tip)

        orient_row = QHBoxLayout()
        portrait_radio = QRadioButton("竖屏", dlg)
        landscape_radio = QRadioButton("横屏", dlg)
        orient_group = QButtonGroup(dlg)
        orient_group.addButton(portrait_radio)
        orient_group.addButton(landscape_radio)
        portrait_radio.setChecked(True)
        orient_row.addWidget(portrait_radio)
        orient_row.addWidget(landscape_radio)
        orient_row.addStretch(1)
        right.addLayout(orient_row)

        title_style = dict(load_overlay_title_from_cfg())
        disc_style = dict(load_overlay_disclaimer_from_cfg())
        state = {
            "title": title_style,
            "disclaimer": disc_style,
            "orientation": "portrait",
            "syncing": False,
        }

        def _build_section(title: str, key: str) -> dict:
            box = QGroupBox(title, dlg)
            form = QFormLayout(box)

            text_edit = LineEdit(box)
            text_edit.setClearButtonEnabled(True)

            font_combo = QComboBox(box)
            for font_key, label, _filename in FONT_CHOICES:
                font_combo.addItem(label, font_key)

            size_spin = QSpinBox(box)
            size_spin.setRange(8, 200)

            color_row = QHBoxLayout()
            color_edit = LineEdit(box)
            color_btn = PushButton("选色", box)
            color_btn.setFixedWidth(56)

            def _pick_color(_checked=False, edit=color_edit):
                current = QColor(edit.text().strip() or "#FFFFFF")
                chosen = QColorDialog.getColor(current, dlg, "选择颜色")
                if chosen.isValid():
                    edit.setText(chosen.name().upper())

            color_btn.clicked.connect(_pick_color)
            color_row.addWidget(color_edit)
            color_row.addWidget(color_btn)

            opacity_spin = QDoubleSpinBox(box)
            opacity_spin.setRange(0.0, 1.0)
            opacity_spin.setSingleStep(0.05)
            opacity_spin.setDecimals(2)

            layout_row = QHBoxLayout()
            h_radio = QRadioButton("横向", box)
            v_radio = QRadioButton("竖向", box)
            layout_group = QButtonGroup(box)
            layout_group.addButton(h_radio)
            layout_group.addButton(v_radio)
            h_radio.setChecked(True)
            layout_row.addWidget(h_radio)
            layout_row.addWidget(v_radio)
            layout_row.addStretch(1)

            x_spin = QDoubleSpinBox(box)
            x_spin.setRange(0.0, 100.0)
            x_spin.setSingleStep(0.5)
            x_spin.setDecimals(1)
            x_spin.setSuffix(" %")

            y_spin = QDoubleSpinBox(box)
            y_spin.setRange(0.0, 100.0)
            y_spin.setSingleStep(0.5)
            y_spin.setDecimals(1)
            y_spin.setSuffix(" %")

            form.addRow("文案：", text_edit)
            form.addRow("排布：", layout_row)
            form.addRow("字体：", font_combo)
            form.addRow("字号：", size_spin)
            form.addRow("颜色：", color_row)
            form.addRow("透明度：", opacity_spin)
            form.addRow("位置 X：", x_spin)
            form.addRow("位置 Y：", y_spin)
            right.addWidget(box)
            return {
                "box": box,
                "text": text_edit,
                "layout_h": h_radio,
                "layout_v": v_radio,
                "font": font_combo,
                "fontsize": size_spin,
                "color": color_edit,
                "opacity": opacity_spin,
                "x_pct": x_spin,
                "y_pct": y_spin,
                "key": key,
            }

        title_w = _build_section("剧名文字", "title")
        disc_w = _build_section("提示文字", "disclaimer")

        def _fill_section(widgets: dict, style: dict):
            state["syncing"] = True
            try:
                widgets["text"].setText(style.get("text", ""))
                if str(style.get("layout") or "horizontal") == "vertical":
                    widgets["layout_v"].setChecked(True)
                else:
                    widgets["layout_h"].setChecked(True)
                idx = widgets["font"].findData(style.get("font"))
                widgets["font"].setCurrentIndex(idx if idx >= 0 else 0)
                widgets["fontsize"].setValue(int(style.get("fontsize") or 16))
                widgets["color"].setText(style.get("color") or "#FFFFFF")
                widgets["opacity"].setValue(float(style.get("opacity") or 1.0))
                pos = position_for_orientation(style, state["orientation"])
                widgets["x_pct"].setValue(float(pos["x_pct"]))
                widgets["y_pct"].setValue(float(pos["y_pct"]))
            finally:
                state["syncing"] = False

        def _read_shared(widgets: dict, style: dict) -> dict:
            out = dict(style)
            out["text"] = widgets["text"].text()
            out["layout"] = (
                "vertical" if widgets["layout_v"].isChecked() else "horizontal"
            )
            out["font"] = widgets["font"].currentData()
            out["fontsize"] = widgets["fontsize"].value()
            out["color"] = widgets["color"].text().strip()
            out["opacity"] = widgets["opacity"].value()
            out = set_position_for_orientation(
                out,
                state["orientation"],
                widgets["x_pct"].value(),
                widgets["y_pct"].value(),
            )
            return out

        def _refresh_preview():
            preview.set_orientation(state["orientation"])
            preview.set_styles(state["title"], state["disclaimer"])

        def _on_param_changed(_value=None):
            if state["syncing"]:
                return
            state["title"] = _read_shared(title_w, state["title"])
            state["disclaimer"] = _read_shared(disc_w, state["disclaimer"])
            _refresh_preview()

        def _wire(widgets: dict):
            widgets["text"].textChanged.connect(_on_param_changed)
            widgets["layout_h"].toggled.connect(_on_param_changed)
            widgets["layout_v"].toggled.connect(_on_param_changed)
            widgets["font"].currentIndexChanged.connect(_on_param_changed)
            widgets["fontsize"].valueChanged.connect(_on_param_changed)
            widgets["color"].textChanged.connect(_on_param_changed)
            widgets["opacity"].valueChanged.connect(_on_param_changed)
            widgets["x_pct"].valueChanged.connect(_on_param_changed)
            widgets["y_pct"].valueChanged.connect(_on_param_changed)

        _wire(title_w)
        _wire(disc_w)

        def _on_orientation_toggled(_checked=False):
            if not portrait_radio.isChecked() and not landscape_radio.isChecked():
                return
            # 先把当前方向的坐标写回
            if not state["syncing"]:
                state["title"] = _read_shared(title_w, state["title"])
                state["disclaimer"] = _read_shared(disc_w, state["disclaimer"])
            state["orientation"] = (
                "landscape" if landscape_radio.isChecked() else "portrait"
            )
            _fill_section(title_w, state["title"])
            _fill_section(disc_w, state["disclaimer"])
            _refresh_preview()

        portrait_radio.toggled.connect(_on_orientation_toggled)
        landscape_radio.toggled.connect(_on_orientation_toggled)

        def _on_preview_pos(which: str, x_pct: float, y_pct: float):
            key = "title" if which == "title" else "disclaimer"
            state[key] = set_position_for_orientation(
                state[key], state["orientation"], x_pct, y_pct
            )
            widgets = title_w if key == "title" else disc_w
            state["syncing"] = True
            try:
                widgets["x_pct"].setValue(x_pct)
                widgets["y_pct"].setValue(y_pct)
            finally:
                state["syncing"] = False

        def _on_preview_selected(which: str):
            # 轻微高亮对应分组标题区（通过选中框已在预览体现）
            pass

        preview.positionChanged.connect(_on_preview_pos)
        preview.itemSelected.connect(_on_preview_selected)

        btn_row = QHBoxLayout()
        reset_btn = PushButton("重置默认", dlg)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dlg,
        )
        btn_row.addWidget(reset_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(buttons)
        right.addLayout(btn_row)
        right.addStretch(1)
        root.addLayout(right, 2)

        def _reset():
            state["title"] = dict(default_overlay_title())
            state["disclaimer"] = dict(default_overlay_disclaimer())
            _fill_section(title_w, state["title"])
            _fill_section(disc_w, state["disclaimer"])
            _refresh_preview()

        reset_btn.clicked.connect(_reset)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)

        _fill_section(title_w, state["title"])
        _fill_section(disc_w, state["disclaimer"])
        _refresh_preview()

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        state["title"] = _read_shared(title_w, state["title"])
        state["disclaimer"] = _read_shared(disc_w, state["disclaimer"])
        title_c, disc_c = save_overlay_styles_to_cfg(state["title"], state["disclaimer"])
        self.vm.save_overlay_text_settings(
            overlay_title=dict(title_c),
            overlay_disclaimer=dict(disc_c),
        )
        show_toast(self, "画面文字设置已保存", title="画面文字")

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
        tag = self.export_name_tag_input.text().strip()
        qconfig.set(cfg.clip_export_name_tag, tag)
        self._update_export_name_preview()
        self.vm.save_export_name_tag(tag)

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
            "选择剧集文件夹",
            start,
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )
        if folder:
            # 记住上一级目录，下次可直接挑选同目录下的其他剧
            parent = os.path.dirname(folder.rstrip("\\/"))
            remember = parent if parent and os.path.isdir(parent) else folder
            qconfig.set(cfg.clip_last_import_dir, remember)
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
            self.batch_all_btn,
            self.batch_transcribe_btn,
            self.batch_plan_btn,
            self.batch_render_btn,
            self.import_btn,
            self.plan_settings_btn,
            self.overlay_text_btn,
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
