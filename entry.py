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

# 尽早显示原生闪屏（不依赖 Qt/torch），避免长时间黑屏无反馈
from app.common.startup_splash import close_startup_splash, show_startup_splash  # noqa: E402

_splash = show_startup_splash("剪辑助手启动中，请稍候…")

# --- 为 Nuitka nofollow 的 torch 子包添加文件系统回退加载 ---
# torch._dynamo 和 torch._inductor 无法被 Nuitka 稳定编译（--nofollow-import-to），
# 但 Nuitka 编译后的 torch 不会自动回退到文件系统加载其子包，需要自定义 import hook。
import importlib.machinery  # noqa: E402
import importlib.abc  # noqa: E402

_TORCH_NOFOLLOW_FALLBACK = {"torch._dynamo", "torch._inductor"}

class _NuitkaSubpackageFallback(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        parts = fullname.split(".")
        # 只处理 torch._dynamo / torch._inductor 及其子模块
        if len(parts) >= 2 and ".".join(parts[:2]) in _TORCH_NOFOLLOW_FALLBACK:
            return importlib.machinery.PathFinder.find_spec(fullname, path, target)
        return None

sys.meta_path.insert(0, _NuitkaSubpackageFallback())

# 冻结的标准库包（如 logging）缺少子模块时，从 dist 目录回退加载
from app.common.nuitka_stdlib_fallback import install_dist_stdlib_importer  # noqa: E402
from app.common.win_subprocess import install_silent_subprocess  # noqa: E402

install_dist_stdlib_importer()
# 尽早静默子进程，避免 FunASR/ffmpeg 等弹出 CMD 黑框
install_silent_subprocess()

# 仅用内置路径改 PATH，禁止在此 import config/Qt（否则会抢在 torch 前加载 PySide6 → WinError 1114）
from app.common.ffmpeg_paths import ensure_bundled_ffmpeg_on_path  # noqa: E402

ensure_bundled_ffmpeg_on_path()

# 必须在 PySide6 之前导入 torch，否则会因 DLL 加载顺序冲突导致 WinError 1114
_splash.set_text("正在加载运行环境…")
import torch  # noqa: E402

_splash.set_text("正在加载界面…")
from PySide6.QtCore import Qt, QTranslator  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.common.config import cfg  # noqa: E402
from app.common.my_logger import my_logger as logger  # noqa: E402
from app.common.utils import show_dialog  # noqa: E402
from app.core.container import Container  # noqa: E402
from app.core.playwright_worker import shutdown_playwright_worker  # noqa: E402
from app.data.services.usage_service import UsageService  # noqa: E402
from app.ui.views.login.view import LoginWindow  # noqa: E402
from app.ui.views.main_window.view import MainWindow  # noqa: E402

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
            close_startup_splash()
            if _run_main_window(MainWindow()):
                continue
            break
        login_window = LoginWindow()
        close_startup_splash()
        if login_window.exec() == LoginWindow.DialogCode.Accepted:
            if _run_main_window(MainWindow()):
                continue
            break
        else:
            break


try:
    main()
except Exception as e:
    close_startup_splash()
    logger.exception(e)
    try:
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            traceback.print_exc(file=f)
    except Exception:
        pass
    show_dialog(parent=None, content='程序出现异常，请尝试重新运行！')
finally:
    close_startup_splash()
    shutdown_playwright_worker()
