import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
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
    qconfig,
)

from app.common.config import cfg
from app.common.export_paths import build_clip_export_filename, resolve_clip_export_root
from app.common.utils import setup_confirm_dialog, show_dialog, show_toast
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
        self.encode_settings_btn = PushButton(
            FIF.SETTING, "编码设置", self.scroll_widget
        )
        self.encode_settings_btn.setToolTip(
            "设置 GPU / CPU 编码档位（默认 p5 / superfast，可选更快档位）"
        )
        self.encode_settings_btn.clicked.connect(self._open_encode_settings)
        batch_row.addWidget(self.import_btn)
        batch_row.addWidget(self.encode_settings_btn)
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
        self._refresh_table(self.vm.get_projects())

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
                    item.setForeground(Qt.GlobalColor.darkGreen)
                elif s == DramaStatus.IN_PROGRESS:
                    item.setForeground(Qt.GlobalColor.darkYellow)
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
        qconfig.set(cfg.clip_export_name_tag, self.export_name_tag_input.text().strip())
        self._update_export_name_preview()

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
            item.setForeground(Qt.GlobalColor.darkYellow)
            break

    def _handle_loading(self, loading: bool, title: str, content: str):
        self._busy = loading
        for w in (
            self.export_browse_btn,
            self.export_open_btn,
            self.export_name_tag_input,
            self.batch_all_btn,
            self.batch_transcribe_btn,
            self.batch_plan_btn,
            self.batch_render_btn,
            self.import_btn,
            self.encode_settings_btn,
            self.table,
        ):
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
