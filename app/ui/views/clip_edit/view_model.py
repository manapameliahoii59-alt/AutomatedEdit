import uuid

from PySide6.QtCore import Signal

from app.core.task_manager import task_manager
from app.core.view_model import ViewModel
from app.data.models.drama_project import DramaProject, DramaStatus
from app.data.services.drama_folder_service import DramaFolderError, scan_drama_folder
from app.data.services.transcription_service import TranscriptionService
from app.data.services.ai_director_service import AIDirectorService
from app.data.services.render_service import RenderService


class ClipEditViewModel(ViewModel):
    projectsChanged = Signal(list)
    loadingChanged = Signal(bool)
    messageReceived = Signal(str)
    errorOccurred = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._projects: list[DramaProject] = []
        self._status: dict[str, dict] = {}
        self.projectsChanged.emit(self._projects)

    def get_projects(self) -> list[DramaProject]:
        return list(self._projects)

    def _ensure_status(self, project_id: str) -> dict:
        if project_id not in self._status:
            self._status[project_id] = {
                "transcribe": DramaStatus.PENDING,
                "plan": DramaStatus.PENDING,
                "render": DramaStatus.PENDING,
            }
        return self._status[project_id]

    def _update_status(self, project_id: str, step: str, status: DramaStatus):
        st = self._ensure_status(project_id)
        st[step] = status
        self.projectsChanged.emit(self._projects)

    def remove_project(self, project_id: str):
        self._projects = [p for p in self._projects if p.id != project_id]
        self._status.pop(project_id, None)
        self.projectsChanged.emit(self._projects)

    def import_drama_folder(self, folder_path: str):
        try:
            scan = scan_drama_folder(folder_path)
        except DramaFolderError as exc:
            self.errorOccurred.emit(str(exc))
            return

        existing = next(
            (p for p in self._projects if p.folder_path == scan.folder_path), None
        )
        if existing:
            existing.name = scan.name
            existing.episode_count = scan.episode_count
            existing.video_files = scan.video_files
            self._status[existing.id] = {
                "transcribe": DramaStatus.PENDING,
                "plan": DramaStatus.PENDING,
                "render": DramaStatus.PENDING,
            }
            self.projectsChanged.emit(self._projects)
            self.messageReceived.emit(f"已更新《{scan.name}》，共 {scan.episode_count} 集。")
            return

        project = DramaProject(
            id=uuid.uuid4().hex,
            name=scan.name,
            episode_count=scan.episode_count,
            folder_path=scan.folder_path,
            video_files=scan.video_files,
        )
        self._projects.append(project)
        self._ensure_status(project.id)
        self.projectsChanged.emit(self._projects)
        self.messageReceived.emit(f"已导入《{scan.name}》，共 {scan.episode_count} 集。")

    def start_transcribe(self, project_id: str):
        project = next((p for p in self._projects if p.id == project_id), None)
        if not project:
            self.errorOccurred.emit("未找到该剧目")
            return

        self._update_status(project_id, "transcribe", DramaStatus.IN_PROGRESS)
        self.loadingChanged.emit(True)

        def _do():
            TranscriptionService.transcribe(project)
            return True

        def _on_success(_ok):
            self.loadingChanged.emit(False)
            self._update_status(project_id, "transcribe", DramaStatus.DONE)
            self.messageReceived.emit(f"《{project.name}》听写完成")

        def _on_error(msg):
            self.loadingChanged.emit(False)
            self._update_status(project_id, "transcribe", DramaStatus.PENDING)
            self.errorOccurred.emit(f"听写失败：{msg}")

        task_manager.submit_task(
            _do,
            on_success=_on_success,
            on_error=_on_error,
        )

    def start_planning(self, project_id: str):
        project = next((p for p in self._projects if p.id == project_id), None)
        if not project:
            self.errorOccurred.emit("未找到该剧目")
            return

        st = self._ensure_status(project_id)
        if st.get("transcribe") != DramaStatus.DONE:
            self.messageReceived.emit("请先完成听写台词")
            return

        self._update_status(project_id, "plan", DramaStatus.IN_PROGRESS)
        self.loadingChanged.emit(True)

        def _do():
            AIDirectorService.plan(project)
            return True

        def _on_success(_ok):
            self.loadingChanged.emit(False)
            self._update_status(project_id, "plan", DramaStatus.DONE)
            self.messageReceived.emit(f"《{project.name}》策划完成")

        def _on_error(msg):
            self.loadingChanged.emit(False)
            self._update_status(project_id, "plan", DramaStatus.PENDING)
            self.errorOccurred.emit(f"策划失败：{msg}")

        task_manager.submit_task(
            _do,
            on_success=_on_success,
            on_error=_on_error,
        )

    def start_render(self, project_id: str):
        project = next((p for p in self._projects if p.id == project_id), None)
        if not project:
            self.errorOccurred.emit("未找到该剧目")
            return

        st = self._ensure_status(project_id)
        if st.get("plan") != DramaStatus.DONE:
            self.messageReceived.emit("请先完成 AI 策划")
            return

        self._update_status(project_id, "render", DramaStatus.IN_PROGRESS)
        self.loadingChanged.emit(True)

        def _do():
            RenderService.render(project)
            return True

        def _on_success(_ok):
            self.loadingChanged.emit(False)
            self._update_status(project_id, "render", DramaStatus.DONE)
            self.messageReceived.emit(f"《{project.name}》渲染完成，请查看项目 outputs 目录")

        def _on_error(msg):
            self.loadingChanged.emit(False)
            self._update_status(project_id, "render", DramaStatus.PENDING)
            self.errorOccurred.emit(f"渲染失败：{msg}")

        task_manager.submit_task(
            _do,
            on_success=_on_success,
            on_error=_on_error,
        )
