import sys
from PySide6.QtCore import QRect, QTimer
from PySide6.QtGui import QIcon
from qfluentwidgets import FluentWindow, NavigationItemPosition, FluentIcon as FIF, qconfig

from app.common.config import cfg
from app.core.container import Container
from app.core.navigation import LazyViewProxy
from app.data.services.access_control_service import access_control
from app.data.services.usage_service import UsageService
from app.ui.views.clip_edit.view import ClipEditPage
from app.ui.views.settings.view import SettingInterface
from app.ui.views.video_download.view import VideoDownloadPage

class MainWindow(FluentWindow):
    """ 主界面 (Refactored) """

    def __init__(self):
        super().__init__()
        self.is_logout = False
        self.init_window()
        self.init_navigation()
        access_control.refresh()

    def init_window(self):
        if sys.platform != "darwin":
            self.setWindowIcon(QIcon(':/resource/images/logo.png'))
            self.setWindowTitle('MyApp')
        self.resize(1200, 800)
        
        # Center window
        if self.screen():
            self.move((self.screen().size().width() - self.width()) / 2,
                      (self.screen().size().height() - self.height()) / 2)
            
        if sys.platform == "darwin":
            self.navigationInterface.panel.setReturnButtonVisible(False)
            self.navigationInterface.panel.topLayout.setContentsMargins(4, 24, 4, 0)
        else:
            self.navigationInterface.setExpandWidth(150)

    def init_navigation(self):
        # Use LazyViewProxy for lazy loading
        # self.batchEditPage = LazyViewProxy(lambda: BatchEditPage(self), "batchEditPage")
        self.clipEditPage = LazyViewProxy(lambda: ClipEditPage(self), "clipEditPage")
        self.videoDownloadPage = LazyViewProxy(lambda: VideoDownloadPage(self), "videoDownloadPage")
        # self.settingInterface = LazyViewProxy(lambda: SettingInterface(self), "settingInterface")
        self.settingInterface = SettingInterface(self)
        self.settingInterface.logout.connect(self.logout)

        self._access_timer = QTimer(self)
        self._access_timer.setInterval(60_000)
        self._access_timer.timeout.connect(self._check_access)
        self._access_timer.start()

        # self.addSubInterface(self.batchEditPage, MyIcon.TOOL, '批量打码')
        self.addSubInterface(self.videoDownloadPage, FIF.DOWNLOAD, '视频下载')
        self.addSubInterface(self.clipEditPage, FIF.VIDEO, '自动化剪辑')
        
        self.addSubInterface(self.settingInterface, FIF.SETTING, '设置', NavigationItemPosition.BOTTOM)

        QTimer.singleShot(0, lambda: self.navigationInterface.expand(useAni=False))

    def _check_access(self) -> None:
        access_control.refresh()

    def handoff_to_clip_edit(self, folder_paths: list[str]) -> None:
        """下载识别完成后，导入剪辑页并执行策划与渲染。"""
        if not folder_paths:
            return
        page = self.clipEditPage.ensure_loaded()
        self.switchTo(self.clipEditPage)
        page.vm.import_and_run_clip_pipeline(folder_paths)

    def import_to_clip_edit(self, folder_paths: list[str]) -> None:
        """将下载目录中的剧目导入自动化剪辑页（不执行后续流程）。"""
        if not folder_paths:
            return
        page = self.clipEditPage.ensure_loaded()
        self.switchTo(self.clipEditPage)
        page.vm.import_drama_folders(folder_paths)

    def logout(self):
        qconfig.set(cfg.auto_login, False)
        Container.auth_service().logout()
        self.is_logout = True
        self.close()

    def closeEvent(self, event):
        UsageService.report_app_close()
        super().closeEvent(event)

    def systemTitleBarRect(self, size):
        return QRect(0, 0, 75, size.height())
