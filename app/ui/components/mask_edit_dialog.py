from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, FluentStyleSheet, SubtitleLabel
from qframelesswindow import FramelessDialog

from app.common.utils import set_window_center
from app.data.models.drama_project import DramaProject
from app.data.services.drama_folder_service import DramaFolderError, scan_drama_folder
from app.ui.components.three_stage_mask_widget import ThreeStageMaskWidget


def resolve_video_files(project: DramaProject) -> list[str]:
    if project.video_files:
        return list(project.video_files)
    if not project.folder_path:
        return []
    try:
        return list(scan_drama_folder(project.folder_path).video_files)
    except DramaFolderError:
        return []


class MaskEditDialog(FramelessDialog):
    """单部剧的打码弹窗：独立模态窗口，内含三段式打码组件。"""

    finished_ok = Signal(object)

    _DIALOG_WIDTH = 1280
    _DIALOG_HEIGHT = 880
    _DIALOG_MIN_WIDTH = 1024
    _DIALOG_MIN_HEIGHT = 720

    def __init__(self, project: DramaProject, parent=None):
        self.project = project
        super().__init__(parent=parent)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._init_ui()
        self.setResizeEnabled(True)
        self.setMinimumSize(self._DIALOG_MIN_WIDTH, self._DIALOG_MIN_HEIGHT)
        self.resize(self._DIALOG_WIDTH, self._DIALOG_HEIGHT)
        FluentStyleSheet.DIALOG.apply(self)
        set_window_center(self)
        QApplication.instance().installEventFilter(self)

    def _init_ui(self):
        self.setWindowTitle(f"打码 · {self.project.name}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 16)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel(self.project.name, self))
        video_files = resolve_video_files(self.project)
        episode_hint = (
            f"共 {len(video_files)} 集"
            if video_files
            else f"共 {self.project.episode_count} 集（未扫描到视频）"
        )
        header.addWidget(BodyLabel(episode_hint, self))
        header.addStretch(1)
        layout.addLayout(header)

        self.mask_widget = ThreeStageMaskWidget(self)
        layout.addWidget(self.mask_widget, 1)
        self.mask_widget.load_episodes(video_files)

        self.mask_widget.confirmed.connect(self._on_confirm)
        self.mask_widget.cancelled.connect(self.reject)
        self.titleBar.raise_()

    def eventFilter(self, watched, event):
        if (
            event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Space
            and self.isVisible()
        ):
            focus = QApplication.focusWidget()
            if focus is not None:
                focus_window = focus.window()
                if focus_window is not None and focus_window is not self:
                    return super().eventFilter(watched, event)
            editor = self.mask_widget.editor
            if not editor._shortcut_blocked() and isinstance(watched, QWidget):
                if watched is self or self.isAncestorOf(watched):
                    editor._toggle_playback_if_allowed()
                    return True
        return super().eventFilter(watched, event)

    def done(self, code):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().done(code)

    def _on_confirm(self, export_path: str):
        self.mask_widget.editor._persist_current_episode()
        episodes = []
        for path in self.mask_widget.editor.episode_list._paths:
            regions = self.mask_widget.editor._episode_states.get(path, [])
            episodes.append((path, list(regions)))
        self.finished_ok.emit({
            "project_id": self.project.id,
            "export_dir": export_path,
            "episodes": episodes,
        })
        self.accept()

    def showEvent(self, event):
        self.mask_widget.reset_stages()
        video_files = resolve_video_files(self.project)
        self.mask_widget.load_episodes(video_files)
        super().showEvent(event)
        self.mask_widget.editor.setFocus(Qt.FocusReason.OtherFocusReason)
