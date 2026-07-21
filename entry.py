import os
import sys
import time
import traceback

# --- 启动诊断 / 崩溃日志（无控制台时尤为重要；仅用标准库）---
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_CRASH_LOG = os.path.join(_APP_DIR, "crash.log")
_STARTUP_LOG = os.path.join(_APP_DIR, "startup.log")
_STARTUP_T0 = time.perf_counter()


def _startup_log(msg: str) -> None:
    """写入启动步骤轨迹，供客户机秒退时排查。失败时静默。"""
    try:
        elapsed_ms = int((time.perf_counter() - _STARTUP_T0) * 1000)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(_STARTUP_LOG, "a", encoding="utf-8") as f:
            f.write(f"{ts} +{elapsed_ms}ms {msg}\n")
    except Exception:
        pass


def _write_crash_log(exc_type, exc_value, exc_tb):
    try:
        _startup_log(f"FATAL {exc_type.__name__}: {exc_value}")
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(f"FATAL: {exc_type.__name__}: {exc_value}\n")
            traceback.print_tb(exc_tb, file=f)
            f.write("\n")
    except Exception:
        pass  # 不能再出错了


# 每次启动新开一段，避免无限膨胀难读
try:
    with open(_STARTUP_LOG, "w", encoding="utf-8") as _sf:
        _sf.write(
            f"==== startup {time.strftime('%Y-%m-%d %H:%M:%S')} "
            f"pid={os.getpid()} ====\n"
        )
except Exception:
    pass

_startup_log(f"process start argv0={sys.argv[0]!r}")
_startup_log(f"python={sys.version.split()[0]} platform={sys.platform}")

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
_startup_log("show splash begin")
from app.common.startup_splash import close_startup_splash, show_startup_splash  # noqa: E402

_splash = show_startup_splash("剪辑助手启动中，请稍候…")
_startup_log("show splash done")

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
_startup_log("install stdlib importer / silent subprocess")
from app.common.nuitka_stdlib_fallback import install_dist_stdlib_importer  # noqa: E402
from app.common.win_subprocess import install_silent_subprocess  # noqa: E402

install_dist_stdlib_importer()
# 尽早静默子进程，避免 FunASR/ffmpeg 等弹出 CMD 黑框
install_silent_subprocess()

# 仅用内置路径改 PATH，禁止在此 import config/Qt（否则会抢在 torch 前加载 PySide6 → WinError 1114）
from app.common.ffmpeg_paths import ensure_bundled_ffmpeg_on_path  # noqa: E402

_startup_log("ensure bundled ffmpeg on PATH begin")
ensure_bundled_ffmpeg_on_path()
_startup_log("ensure bundled ffmpeg on PATH done")

# 必须在 PySide6 之前导入 torch，否则会因 DLL 加载顺序冲突导致 WinError 1114
_splash.set_text("正在加载运行环境…")
_startup_log("import torch begin")
import torch  # noqa: E402
_startup_log("import torch done")

_splash.set_text("正在加载界面…")
_startup_log("import PySide6 begin")
from PySide6.QtCore import Qt, QTranslator  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
_startup_log("import PySide6 done")

_startup_log("import app modules begin")
from app.common.config import cfg  # noqa: E402
from app.common.my_logger import my_logger as logger  # noqa: E402
from app.common.utils import show_dialog  # noqa: E402
from app.core.container import Container  # noqa: E402
from app.core.playwright_worker import shutdown_playwright_worker  # noqa: E402
from app.data.services.usage_service import UsageService  # noqa: E402
from app.ui.views.login.view import LoginWindow  # noqa: E402
from app.ui.views.main_window.view import MainWindow  # noqa: E402
_startup_log("import app modules done")

# 适配缩放比例
QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
_startup_log("QApplication create begin")
app = QApplication(sys.argv)
_startup_log("QApplication create done")
font = app.font()
font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
app.setFont(font)
app.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)
translator = QTranslator()
translator.load(":/resource/i18n/zh.qm")
app.installTranslator(translator)
app.aboutToQuit.connect(shutdown_playwright_worker)
_startup_log("QApplication setup done")


def _run_main_window(main_window: MainWindow) -> bool:
    """显示主窗口，返回是否为退出登录（需重新登录）。"""
    _startup_log("main window show begin")
    UsageService.report_app_login()
    main_window.show()
    _startup_log("main window show done, enter event loop")
    app.exec()
    return bool(getattr(main_window, "is_logout", False))


def main():
    _startup_log("main() begin")
    auth = Container.auth_service()
    while True:
        if cfg.auto_login.value and auth.try_auto_login():
            _startup_log("auto login success")
            logger.debug('自动登录成功')
            close_startup_splash()
            if _run_main_window(MainWindow()):
                continue
            break
        _startup_log("show login window")
        login_window = LoginWindow()
        close_startup_splash()
        if login_window.exec() == LoginWindow.DialogCode.Accepted:
            _startup_log("login accepted")
            if _run_main_window(MainWindow()):
                continue
            break
        else:
            _startup_log("login cancelled / rejected")
            break
    _startup_log("main() end")


try:
    main()
except Exception as e:
    _startup_log(f"main() exception: {type(e).__name__}: {e}")
    close_startup_splash()
    logger.exception(e)
    try:
        with open(_CRASH_LOG, "a", encoding="utf-8") as f:
            traceback.print_exc(file=f)
    except Exception:
        pass
    show_dialog(parent=None, content='程序出现异常，请尝试重新运行！')
finally:
    _startup_log("shutdown begin")
    close_startup_splash()
    shutdown_playwright_worker()
    _startup_log("shutdown done")
