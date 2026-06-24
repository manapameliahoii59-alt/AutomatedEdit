import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    Dialog,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SubtitleLabel,
    TableWidget,
    FluentIcon as FIF,
    qconfig,
)

from app.common.config import cfg
from app.common.export_paths import resolve_clip_export_root
from app.common.utils import show_dialog
from app.data.models.drama_project import DramaProject, DramaStatus
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
                "导入剧集后，依次执行「听写台词 → AI导演策划 → 动态渲染」三步。",
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

        batch_row = QHBoxLayout()
        batch_row.setSpacing(8)
        self.batch_all_btn = PrimaryPushButton("一键执行", self.scroll_widget)
        self.batch_all_btn.clicked.connect(self._batch_all)
        self.batch_transcribe_btn = PushButton("批量听写", self.scroll_widget)
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
        batch_row.addWidget(self.import_btn)
        batch_row.addStretch(1)
        layout.addLayout(batch_row)

        self.table = TableWidget(self.scroll_widget)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["", "剧名", "集数", "听写", "策划", "渲染", "操作"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(TableWidget.SelectionMode.SingleSelection)
        layout.addWidget(self.table, 1)

        self.setViewportMargins(0, 0, 0, 0)

    def _bind_view_model(self):
        self.vm.projectsChanged.connect(self._refresh_table)
        self.vm.loadingChanged.connect(self._handle_loading)
        self.vm.messageReceived.connect(lambda msg: show_dialog(self, msg, "提示"))
        self.vm.errorOccurred.connect(lambda msg: show_dialog(self, msg, "提示"))
        self._refresh_table(self.vm.get_projects())

    def _refresh_table(self, projects: list[DramaProject]):
        self.table.setRowCount(len(projects))
        for row, project in enumerate(projects):
            st = self.vm._status.get(project.id, {})

            check_item = QTableWidgetItem()
            check_item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            check_item.setCheckState(Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, check_item)

            self.table.setItem(row, 1, QTableWidgetItem(project.name))
            self.table.setItem(row, 2, QTableWidgetItem(str(project.episode_count)))

            for col, key in [(3, "transcribe"), (4, "plan"), (5, "render")]:
                s = st.get(key, DramaStatus.PENDING)
                item = QTableWidgetItem(STATUS_LABELS.get(s, "待处理"))
                if s == DramaStatus.DONE:
                    item.setForeground(Qt.GlobalColor.darkGreen)
                elif s == DramaStatus.IN_PROGRESS:
                    item.setForeground(Qt.GlobalColor.darkYellow)
                self.table.setItem(row, col, item)

            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(4, 0, 4, 0)

            transcribe_btn = PushButton("听写", cell)
            transcribe_btn.setProperty("project_id", project.id)
            transcribe_btn.clicked.connect(
                lambda _=False, pid=project.id: self.vm.start_transcribe(pid)
            )

            plan_btn = PushButton("策划", cell)
            plan_btn.setProperty("project_id", project.id)
            plan_btn.clicked.connect(
                lambda _=False, pid=project.id: self.vm.start_planning(pid)
            )

            render_btn = PushButton("渲染", cell)
            render_btn.setProperty("project_id", project.id)
            render_btn.clicked.connect(
                lambda _=False, pid=project.id: self.vm.start_render(pid)
            )

            del_btn = PushButton("删除", cell)
            del_btn.setProperty("project_id", project.id)
            del_btn.clicked.connect(
                lambda _=False, pid=project.id: self._confirm_delete(pid)
            )

            cell_layout.addWidget(transcribe_btn)
            cell_layout.addWidget(plan_btn)
            cell_layout.addWidget(render_btn)
            cell_layout.addWidget(del_btn)
            self.table.setCellWidget(row, 6, cell)

        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, 40)

    def _get_checked_ids(self) -> list[str]:
        projects = self.vm.get_projects()
        ids = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                if row < len(projects):
                    ids.append(projects[row].id)
        return ids

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

    def _batch_all(self):
        ids = [p.id for p in self.vm.get_projects()]
        if not ids:
            show_dialog(self, "暂未导入任何剧目", "提示")
            return
        w = Dialog(
            "一键执行",
            f"确认对全部 {len(ids)} 个剧目执行「听写台词 → AI导演策划 → 动态渲染」完整流程吗？",
            self.window(),
        )
        w.yesButton.setText("确定")
        w.cancelButton.setText("取消")
        w.buttonLayout.insertWidget(0, w.cancelButton)
        w.yesButton.setMinimumWidth(110)
        w.cancelButton.setMinimumWidth(110)

        close_btn = PushButton("×", w)
        close_btn.setFixedSize(32, 32)
        close_btn.clicked.connect(w.close)
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.addStretch(1)
        top_bar.addWidget(close_btn)
        w.vBoxLayout.insertLayout(0, top_bar)

        if w.exec():
            try:
                self.vm.batch_all(ids)
            except Exception as e:
                show_dialog(self, f"一键执行失败：{e}", "错误")

    def _confirm_delete(self, project_id: str):
        project = next((p for p in self.vm.get_projects() if p.id == project_id), None)
        if not project:
            return
        w = Dialog("删除剧目", f"确定要删除《{project.name}》吗？", self.window())
        w.yesButton.setText("确定")
        w.cancelButton.setText("取消")
        if w.exec():
            self.vm.remove_project(project_id)

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
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择剧集文件夹",
            "",
            QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
        )
        if folder:
            self.vm.import_drama_folder(folder)

    def _handle_loading(self, is_loading: bool):
        if is_loading:
            self._show_loading("正在处理", "请稍候...")
        else:
            self._close_loading()

    def _show_loading(self, title, content):
        self.loading_bar = ProgressInfoBar(title, content, self)
        self.loading_bar.show()

    def _close_loading(self):
        if self.loading_bar:
            self.loading_bar.hide()
            self.loading_bar = None
