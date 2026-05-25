from PySide6.QtCore import Signal

from app.core.view_model import ViewModel
from app.data.models.drama_project import DramaProject, DramaStatus


class BatchEditViewModel(ViewModel):
    projectsChanged = Signal(list)
    messageReceived = Signal(str)
    errorOccurred = Signal(str)
    openMaskDialog = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._projects: list[DramaProject] = []
        self._load_demo_projects()

    def _load_demo_projects(self):
        """占位数据：后续改为扫描文件夹或读取任务配置。"""
        self._projects = [
            DramaProject("1", "霸道总裁爱上我", 12, r"D:\videos\drama_01"),
            DramaProject("2", "重生之我在古代当厨神", 8, r"D:\videos\drama_02"),
            DramaProject("3", "都市异能觉醒记", 15, r"D:\videos\drama_03"),
            DramaProject("4", "校园恋爱物语", 10, r"D:\videos\drama_04"),
        ]
        self.projectsChanged.emit(self._projects)

    def get_projects(self) -> list[DramaProject]:
        return list(self._projects)

    def start_mask_for_project(self, project_id: str):
        project = next((p for p in self._projects if p.id == project_id), None)
        if not project:
            self.errorOccurred.emit("未找到该剧目")
            return
        if project.status == DramaStatus.DONE:
            self.messageReceived.emit(f"《{project.name}》已完成，可重新打开修改。")
        project.status = DramaStatus.IN_PROGRESS
        self.projectsChanged.emit(self._projects)
        self.openMaskDialog.emit(project)

    def complete_mask_for_project(self, project_id: str):
        project = next((p for p in self._projects if p.id == project_id), None)
        if not project:
            return
        project.status = DramaStatus.DONE
        self.projectsChanged.emit(self._projects)
        pending = [p for p in self._projects if p.status != DramaStatus.DONE]
        if pending:
            self.messageReceived.emit(
                f"《{project.name}》已确认。下一部待处理：《{pending[0].name}》"
            )
        else:
            self.messageReceived.emit(f"《{project.name}》已确认，本批次全部完成。")

    def import_batch_folder(self):
        self.messageReceived.emit("导入批次：后续接入文件夹选择并解析多部短剧。")
