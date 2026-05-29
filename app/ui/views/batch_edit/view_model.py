import uuid

from PySide6.QtCore import Signal

from app.core.view_model import ViewModel
from app.data.models.drama_project import DramaProject, DramaStatus
from app.data.services.drama_folder_service import DramaFolderError, scan_drama_folder


class BatchEditViewModel(ViewModel):
    projectsChanged = Signal(list)
    messageReceived = Signal(str)
    errorOccurred = Signal(str)
    openMaskDialog = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._projects: list[DramaProject] = []
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

    def import_drama_folder(self, folder_path: str):
        """从剧集文件夹导入一部短剧（扫描视频文件并加入列表）。"""
        try:
            scan = scan_drama_folder(folder_path)
        except DramaFolderError as exc:
            self.errorOccurred.emit(str(exc))
            return

        existing = next(
            (p for p in self._projects if p.folder_path == scan.folder_path),
            None,
        )
        if existing:
            existing.name = scan.name
            existing.episode_count = scan.episode_count
            existing.video_files = scan.video_files
            existing.status = DramaStatus.PENDING
            self.projectsChanged.emit(self._projects)
            self.messageReceived.emit(
                f"已更新《{scan.name}》，共 {scan.episode_count} 集。"
            )
            return

        project = DramaProject(
            id=uuid.uuid4().hex,
            name=scan.name,
            episode_count=scan.episode_count,
            folder_path=scan.folder_path,
            video_files=scan.video_files,
        )
        self._projects.append(project)
        self.projectsChanged.emit(self._projects)
        self.messageReceived.emit(
            f"已导入《{scan.name}》，共 {scan.episode_count} 集。"
        )
