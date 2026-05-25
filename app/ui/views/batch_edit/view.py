from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QTableWidgetItem, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    PrimaryPushButton,
    PushButton,
    ScrollArea,
    SubtitleLabel,
    TableWidget,
    FluentIcon as FIF,
)

from app.common.utils import show_dialog
from app.data.models.drama_project import DramaProject, DramaStatus
from app.ui.components.mask_edit_dialog import MaskEditDialog

from .view_model import BatchEditViewModel


class BatchEditPage(ScrollArea):
    """批量短剧列表：点击单部剧弹出三段式打码窗口。"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._parent_window = parent
        self.vm = BatchEditViewModel(self)
        self.setObjectName("batch_edit_page")
        self._init_ui()
        self._bind_view_model()

    def _init_ui(self):
        self.scroll_widget = QWidget()
        self.scroll_widget.setObjectName("batchEditScrollWidget")
        self.setWidget(self.scroll_widget)
        self.setWidgetResizable(True)

        layout = QVBoxLayout(self.scroll_widget)
        layout.setContentsMargins(36, 20, 36, 20)
        layout.setSpacing(16)

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel("批量视频打码", self.scroll_widget))
        header.addStretch(1)
        self.import_btn = PrimaryPushButton(FIF.FOLDER_ADD, "导入批次", self.scroll_widget)
        self.import_btn.clicked.connect(self.vm.import_batch_folder)
        header.addWidget(self.import_btn)
        layout.addLayout(header)

        layout.addWidget(
            BodyLabel("点击「开始打码」打开弹窗，完成三段式打码并确认后返回本页继续下一部。", self.scroll_widget)
        )

        self.table = TableWidget(self.scroll_widget)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["剧名", "集数", "状态", "操作"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(TableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(TableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(TableWidget.SelectionMode.SingleSelection)
        layout.addWidget(self.table, 1)

        self.setViewportMargins(0, 0, 0, 0)

    def _bind_view_model(self):
        self.vm.projectsChanged.connect(self._refresh_table)
        self.vm.openMaskDialog.connect(self._open_mask_dialog)
        self.vm.messageReceived.connect(lambda msg: show_dialog(self, msg, "提示"))
        self.vm.errorOccurred.connect(lambda msg: show_dialog(self, msg, "提示"))
        self._refresh_table(self.vm.get_projects())

    def _refresh_table(self, projects: list[DramaProject]):
        self.table.setRowCount(len(projects))
        for row, project in enumerate(projects):
            self.table.setItem(row, 0, QTableWidgetItem(project.name))
            self.table.setItem(row, 1, QTableWidgetItem(str(project.episode_count)))
            status_item = QTableWidgetItem(project.status_label)
            if project.status == DramaStatus.DONE:
                status_item.setForeground(Qt.GlobalColor.darkGreen)
            elif project.status == DramaStatus.IN_PROGRESS:
                status_item.setForeground(Qt.GlobalColor.darkYellow)
            self.table.setItem(row, 2, status_item)

            cell = QWidget()
            cell_layout = QHBoxLayout(cell)
            cell_layout.setContentsMargins(4, 0, 4, 0)
            btn = PushButton("开始打码", cell)
            btn.setProperty("project_id", project.id)
            btn.clicked.connect(lambda _=False, pid=project.id: self.vm.start_mask_for_project(pid))
            cell_layout.addWidget(btn)
            self.table.setCellWidget(row, 3, cell)

        self.table.resizeColumnsToContents()

    def _open_mask_dialog(self, project: DramaProject):
        parent = self._parent_window or self.window()
        dialog = MaskEditDialog(project, parent)
        dialog.finished_ok.connect(self.vm.complete_mask_for_project)
        dialog.exec()
