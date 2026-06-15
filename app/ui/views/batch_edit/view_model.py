import uuid
from pathlib import Path

import cv2
from PySide6.QtCore import Signal

from app.core.task_manager import task_manager
from app.core.view_model import ViewModel
from app.data.models.drama_project import DramaProject, DramaStatus
from app.data.services.drama_folder_service import DramaFolderError, scan_drama_folder
from app.ui.components.masked_video_preview import _apply_masks_to_frame


class BatchEditViewModel(ViewModel):
    projectsChanged = Signal(list)
    loadingChanged = Signal(bool)
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

    def complete_mask_for_project(self, data: dict):
        project_id = data["project_id"]
        project = next((p for p in self._projects if p.id == project_id), None)
        if not project:
            return

        export_dir = data["export_dir"]
        episodes = data["episodes"]

        def _do_export():
            for source_path, regions in episodes:
                src = Path(source_path)
                if not src.is_file():
                    continue
                cap = cv2.VideoCapture(str(src))
                fps = cap.get(cv2.CAP_PROP_FPS)
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                out = Path(export_dir) / src.name
                writer = cv2.VideoWriter(str(out), fourcc, fps, (w, h))
                fi = 0
                while True:
                    ret, frame = cap.read()
                    if not ret:
                        break
                    ms = int(fi / fps * 1000)
                    _apply_masks_to_frame(frame, regions, ms, w, h)
                    writer.write(frame)
                    fi += 1
                cap.release()
                writer.release()
            return True

        self.loadingChanged.emit(True)

        def _on_success(_ok):
            self.loadingChanged.emit(False)
            project.status = DramaStatus.DONE
            self.projectsChanged.emit(self._projects)
            self.messageReceived.emit(f"《{project.name}》导出完成")

        def _on_error(msg):
            self.loadingChanged.emit(False)
            self.errorOccurred.emit(f"导出失败：{msg}")

        task_manager.submit_task(
            _do_export,
            on_success=_on_success,
            on_error=_on_error,
        )

    def remove_project(self, project_id: str):
        self._projects = [p for p in self._projects if p.id != project_id]
        self.projectsChanged.emit(self._projects)

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
