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
)

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
        self.import_btn = PrimaryPushButton(
            FIF.FOLDER_ADD, "导入剧目", self.scroll_widget
        )
        self.import_btn.clicked.connect(self._pick_drama_folder)
        header.addWidget(self.import_btn)
        layout.addLayout(header)

        layout.addWidget(
            BodyLabel(
                "导入剧集后，依次执行「听写台词 → AI导演策划 → 动态渲染」三步。",
                self.scroll_widget,
            )
        )

        self.table = TableWidget(self.scroll_widget)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(
            ["剧名", "集数", "听写", "策划", "渲染", "操作"]
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

            self.table.setItem(row, 0, QTableWidgetItem(project.name))
            self.table.setItem(row, 1, QTableWidgetItem(str(project.episode_count)))

            for col, key in [(2, "transcribe"), (3, "plan"), (4, "render")]:
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
            self.table.setCellWidget(row, 5, cell)

        self.table.resizeColumnsToContents()

    def _confirm_delete(self, project_id: str):
        project = next((p for p in self.vm.get_projects() if p.id == project_id), None)
        if not project:
            return
        w = Dialog("删除剧目", f"确定要删除《{project.name}》吗？", self.window())
        w.yesButton.setText("确定")
        w.cancelButton.setText("取消")
        if w.exec():
            self.vm.remove_project(project_id)

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
