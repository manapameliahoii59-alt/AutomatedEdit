import os

# 须在 QApplication / QMediaPlayer 之前设置，减轻 FFmpeg 探测类警告刷屏
os.environ.setdefault("AV_LOG_LEVEL", "quiet")
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

import sys

# 必须在 PySide6 之前导入 torch，否则会因 DLL 加载顺序冲突导致 WinError 1114
import torch  # noqa: E402

from PySide6.QtCore import Qt, QTranslator
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.common.config import cfg
from app.common.my_logger import my_logger as logger
from app.common.utils import show_dialog
from app.core.container import Container
from app.core.playwright_worker import shutdown_playwright_worker
from app.data.services.usage_service import UsageService
# from view.login_window.window import LoginWindow
from app.ui.views.login.view import LoginWindow
# from view.main_window import MainWindow
from app.ui.views.main_window.view import MainWindow

# 适配缩放比例
QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
app = QApplication(sys.argv)
font = app.font()
font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
app.setFont(font)
app.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings) # 解决弹dialog后frameless窗口无法在调整大小
translator = QTranslator()
translator.load(":/resource/i18n/zh.qm")
app.installTranslator(translator)
app.aboutToQuit.connect(shutdown_playwright_worker)


def _run_main_window(main_window: MainWindow) -> bool:
    """显示主窗口，返回是否为退出登录（需重新登录）。"""
    UsageService.report_app_login()
    main_window.show()
    app.exec()
    return bool(getattr(main_window, "is_logout", False))


def main():
    auth = Container.auth_service()
    while True:
        if cfg.auto_login.value and auth.try_auto_login():
            logger.debug('自动登录成功')
            if _run_main_window(MainWindow()):
                continue
            break
        login_window = LoginWindow()
        if login_window.exec() == LoginWindow.DialogCode.Accepted:
            if _run_main_window(MainWindow()):
                continue
            break
        else:
            break


try:
    main()
except Exception as e:
    logger.exception(e)
    show_dialog(parent=None, content='程序出现异常，请尝试重新运行！')
finally:
    shutdown_playwright_worker()
