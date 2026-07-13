import os
import sys
import traceback

# --- 启动崩溃日志（无控制台时尤为重要）---
_CRASH_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crash.log")

def _write_crash_log(exc_type, exc_value, exc_tb):
    try:
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(f"FATAL: {exc_type.__name__}: {exc_value}\n")
            traceback.print_tb(exc_tb, file=f)
            f.write("\n")
    except Exception:
        pass  # 不能再出错了

sys.excepthook = _write_crash_log

# 未处理的异常也通过 stderr 写入文件
try:
    stderr_fd = open(_CRASH_LOG, "a", encoding="utf-8")
    sys.stderr = stderr_fd
except Exception:
    pass

# 须在 QApplication / QMediaPlayer 之前设置，减轻 FFmpeg 探测类警告刷屏
os.environ.setdefault("AV_LOG_LEVEL", "quiet")
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")

# --- 为 Nuitka nofollow 的 torch 子包添加文件系统回退加载 ---
# torch._dynamo 和 torch._inductor 无法被 Nuitka 稳定编译（--nofollow-import-to），
# 但 Nuitka 编译后的 torch 不会自动回退到文件系统加载其子包，需要自定义 import hook。
import importlib.machinery
import importlib.abc

_TORCH_NOFOLLOW_FALLBACK = {"torch._dynamo", "torch._inductor"}

class _NuitkaSubpackageFallback(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        parts = fullname.split(".")
        # 只处理 torch._dynamo / torch._inductor 及其子模块
        if len(parts) >= 2 and ".".join(parts[:2]) in _TORCH_NOFOLLOW_FALLBACK:
            return importlib.machinery.PathFinder.find_spec(fullname, path, target)
        return None

sys.meta_path.insert(0, _NuitkaSubpackageFallback())

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
from app.ui.views.login.view import LoginWindow
from app.ui.views.main_window.view import MainWindow

# 适配缩放比例
QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
app = QApplication(sys.argv)
font = app.font()
font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
app.setFont(font)
app.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)
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
    try:
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            traceback.print_exc(file=f)
    except Exception:
        pass
    show_dialog(parent=None, content='程序出现异常，请尝试重新运行！')
finally:
    shutdown_playwright_worker()
