import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Try to import config, handle missing dependencies gracefully for build script if possible,
# but since we need VERSION and AUTHOR, we assume dependencies are there.
try:
    from app.common.config import VERSION, AUTHOR, APP_NAME
except ImportError:
    print("Warning: Could not import app.common.config. Using default values.")
    VERSION = "1.0.0"
    AUTHOR = "Unknown"
    APP_NAME = "剪辑助手"
OUT_DIR = PROJECT_ROOT / "out"
DIST_DIR = OUT_DIR / "entry.dist"
SITE_PACKAGES = PROJECT_ROOT / ".venv" / "Lib" / "site-packages"

# Nuitka 无法稳定编译的模块（--nofollow-import-to 会跳过编译，需手动拷贝源码包）
#
# 注意：torch 子包被 nofollow 后，Nuitka 的编译版 torch 不会回退到文件系统加载它们。
# 因此 entry.py 中需要添加自定义 import hook 来兜底加载这些 nofollow 子包的源码。
NUITKA_NOFOLLOW_MODULES = (
    # 不可 nofollow：torch.utils.data 会在 import torch 时加载 distributed
    "transformers",
    "modelscope",
    # funasr 依赖包内 version.txt 等数据文件，编译后易缺失，改为源码拷贝
    "funasr",
    # sentencepiece 的 SWIG 原生扩展 _sentencepiece.pyd 被 Nuitka 编译版包遮蔽后无法加载，
    # 导致 funasr 的 SentencepiecesTokenizer 注册失败（识别时组件未就绪），改为源码拷贝
    "sentencepiece",
    # torch 子包中使用 walrus 操作符等语法，Nuitka 无法稳定编译
    "torch._dynamo",
    "torch._inductor",
    # 纯 Python 庞大库及网络依赖：改为源码拷贝，消除 2000+ 个 C 模块编译开销
    "openai",
    "sympy",
    "pydantic",
    "pydantic_core",
    "annotated_types",
    "anyio",
    "httpx",
    "httpcore",
)

# Nuitka 自带的 MSVC 运行库与 torch 的 c10.dll 不兼容（WinError 1114），需替换为系统版本
VC_RUNTIME_DLLS = (
    "msvcp140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "vcomp140.dll",
)

# nofollow 后需原样拷贝到 dist 的包目录名（含数据文件，如 funasr/version.txt）
NOFOLLOW_COPY_PACKAGES = (
    "transformers",
    "modelscope",
    "funasr",
    "torch._dynamo",
    "torch._inductor",
    "openai",
    "sympy",
    "pydantic",
    "pydantic_core",
    "annotated_types",
    "anyio",
    "httpx",
    "httpcore",
)

# FunASR 为 nofollow 源码包，其传递依赖未必被 Nuitka 跟踪，需一并拷贝
# 支持目录包名，或单文件模块（如 soundfile.py）
FUNASR_RUNTIME_COPY_PACKAGES = (
    "omegaconf",
    "hydra",
    "antlr4",
    "editdistance",
    "jaconv",
    "jamo",
    "jieba",
    "kaldiio",
    "librosa",
    "oss2",
    "aliyunsdkcore",
    "aliyunsdkkms",
    "crcmod",
    "soundfile.py",
    "_soundfile.py",
    "_soundfile_data",
    "tensorboardX",
    "tiktoken",
    "torch_complex",
    "audioread",
    "pooch",
    "soxr",
    "lazy_loader",
    "msgpack",
    "numba",
    "llvmlite",
    "llvmlite.libs",
    "sentencepiece",
    # sentencepiece 的 *_pb2 依赖 google.protobuf（含 _upb/_message.pyd）
    "google",
    "rapidocr_onnxruntime",
    "onnxruntime",
    # modelscope / transformers / funasr 常见传递依赖（Nuitka 常漏）
    "packaging",
    "setuptools",
    "_distutils_hack",
    "pkg_resources",
    "filelock",
    "tqdm",
    "yaml",
    "requests",
    "urllib3",
    "charset_normalizer",
    "*__mypyc*.pyd",
    "typing_extensions.py",
    "idna",
    "certifi",
    "huggingface_hub",
    "safetensors",
    "fsspec",
    "jinja2",
    "markupsafe",
    "six.py",
    # Paraformer / BiCifParaformer -> funasr.utils.load_utils 强依赖
    "torchaudio",
    # openai 与 sympy 运行时传递依赖
    "distro",
    "sniffio",
    "mpmath",
    "typing_inspection",
)

# FunASR / ModelScope / torchaudio 动态 import 的标准库（Nuitka 静态分析常漏掉）
# --include-module 用完整模块名；拷贝用下方 STDLIB_COPY_ITEMS 的顶层名
STDLIB_INCLUDE_MODULES = (
    "wave",
    "chunk",
    "audioop",
    "aifc",
    "sunau",
    "logging",
    "logging.config",
    "logging.handlers",
    "concurrent",
    "concurrent.futures",
    "xml",
    "xml.etree",
    "xml.etree.ElementTree",
    "html",
    "http",
    "urllib",
    "email",
    "csv",
    "configparser",
    "sqlite3",
    "gzip",
    "bz2",
    "lzma",
    "zipfile",
    "tarfile",
    "secrets",
    "fractions",
    "decimal",
    "statistics",
    "zoneinfo",
    "mimetypes",
    "queue",
    "bisect",
    "heapq",
    "numbers",
    "getpass",
    "netrc",
    "plistlib",
)

# 从 CPython Lib/DLLs 拷到 dist 的顶层模块/包（覆盖 include 未编进二进制的情况）
STDLIB_COPY_ITEMS = (
    "wave",
    "chunk",
    "aifc",
    "sunau",
    "logging",
    "concurrent",
    "xml",
    "html",
    "http",
    "urllib",
    "email",
    "csv",
    "configparser",
    "sqlite3",
    "gzip",
    "bz2",
    "lzma",
    "zipfile",
    "tarfile",
    "secrets",
    "fractions",
    "decimal",
    "statistics",
    "zoneinfo",
    "mimetypes",
    "queue",
    "bisect",
    "heapq",
    "numbers",
    "getpass",
    "netrc",
    "plistlib",
    "audioop",
)

# 打包完成后从 dist 删除的无用目录（运行时不需要）
CLEANUP_DIRS = (
    "torch/include",
)


def _warn_if_non_ascii_path() -> None:
    path_text = str(PROJECT_ROOT)
    if not path_text.isascii():
        print(
            "Warning: 项目路径包含非 ASCII 字符，Nuitka/mingw 编译可能失败。"
            f"建议将项目移到纯英文路径后再打包，例如 C:\\dev\\AutomatedEdit\n"
            f"当前路径: {path_text}"
        )


def run_cmd(cmd: str) -> int:
    print(f"Run cmd: {cmd}")
    result = subprocess.run(cmd, shell=True)
    return result.returncode


def build_resources() -> None:
    """Run pack_resources.py"""
    print("Building resources...")
    if run_cmd(f"{sys.executable} scripts/pack_resources.py") != 0:
        sys.exit("Failed to build resources")


def bundle_ffmpeg() -> None:
    src_dir = PROJECT_ROOT / "tools" / "ffmpeg" / "win"
    if not (src_dir / "ffmpeg.exe").is_file():
        env_src = __import__("os").environ.get("FFMPEG_SOURCE_DIR")
        if env_src:
            ext_bin = Path(env_src) / "bin"
            if (ext_bin / "ffmpeg.exe").is_file():
                src_dir.mkdir(parents=True, exist_ok=True)
                for name in ("ffmpeg.exe", "ffprobe.exe"):
                    shutil.copy2(ext_bin / name, src_dir / name)
                license_src = Path(env_src) / "LICENSE"
                if license_src.is_file():
                    shutil.copy2(license_src, src_dir.parent / "LICENSE")

    dst_dir = DIST_DIR / "tools" / "ffmpeg" / "win"
    if not src_dir.is_dir():
        print(f"Warning: {src_dir} not found, skipping FFmpeg bundle")
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        src = src_dir / name
        if src.is_file():
            shutil.copy2(src, dst_dir / name)
            print(f"Bundled {name}")
        else:
            print(f"Warning: {src} not found")
    license_src = PROJECT_ROOT / "tools" / "ffmpeg" / "LICENSE"
    if license_src.is_file():
        shutil.copy2(license_src, dst_dir.parent / "LICENSE")


def bundle_playwright_browsers() -> None:
    """将 Playwright Chromium 浏览器拷贝到 dist，避免用户手动下载。"""
    local_browsers = Path(os.environ["USERPROFILE"]) / "AppData" / "Local" / "ms-playwright"
    dst_base = DIST_DIR / "playwright" / "driver" / "package" / ".local-browsers"

    # 清理之前可能遗留的冗余 headless shell（节省 270MB+ 空间和打包耗时）
    redundant_headless = dst_base / "chromium_headless_shell-1228"
    if redundant_headless.is_dir():
        try:
            shutil.rmtree(redundant_headless)
            print("Removed obsolete chromium_headless_shell from dist")
        except Exception as exc:
            print(f"Warning: failed to remove {redundant_headless}: {exc}")

    # 只打包全功能版 Chromium（支持有头与无头模式）以及辅助工具，移除无用 headless shell
    keep = {"chromium-1228", "ffmpeg-1011", "winldd-1007"}
    for browser_dir in local_browsers.iterdir():
        if not browser_dir.is_dir() or browser_dir.name not in keep:
            continue
        dst = dst_base / browser_dir.name
        # 增量判断：若目标已存在且包含内容，跳过无谓的删除与重新全量拷贝（节省几百 MB 磁盘 IO）
        if dst.is_dir() and any(dst.iterdir()):
            print(f"Bundled Playwright browser already exists, skipping copy: {browser_dir.name}")
            continue
        if dst.exists():
            shutil.rmtree(dst)
        try:
            shutil.copytree(browser_dir, dst)
            print(f"Bundled Playwright browser: {browser_dir.name}")
        except Exception as exc:
            print(f"Warning: failed to bundle {browser_dir.name}: {exc}")


def bundle_config() -> None:
    """写入干净的默认配置，禁止把开发机登录态/密钥打进安装包。"""
    import json

    clean = {
        "API": {
            "access_token": "",
            "base_url": "",
            "plan_decrypt_key": "",
        },
        "MainWindow": {
            "auto_login": False,
            "save_password": True,
        },
        "User": {
            "user": "",
            "password": "",
            "enabled_tabs": "video_download,clip_edit",
        },
        "LLM": {
            "dashscope_api_key": "",
        },
        "Tools": {
            "changdu_email": "",
            "changdu_password": "",
            "clip_auto_retry_failed": True,
            "clip_auto_select_after_import": True,
            "clip_export_dir": "",
            "clip_export_name_tag": "",
            "clip_export_date_format": "md",
            "clip_export_seq_format": "pad2",
            "clip_last_import_dir": "",
            "clip_overlay_bake_png": True,
            "clip_render_engine": "current",
            "clip_trim_ep1_continued": True,
            "overlay_title_json": "",
            "overlay_disclaimer_json": "",
            "overlay_text_library_json": "",
            "encode_amf_preset": "speed",
            "encode_enable_gpu": False,
            "encode_nvenc_preset": "p3",
            "encode_output_resolution": "720p",
            "encode_qsv_preset": "veryfast",
            "encode_x264_preset": "superfast",
            "plan_mode": "mixed",
            "plan_clip_count": 15,
            "plan_max_duration_sec": 720,
            "plan_short_clip_count": 15,
            "plan_short_max_duration_sec": 300,
            "plan_mixed_clip_count": 15,
            "plan_mixed_max_duration_sec": 720,
            "plan_mixed_strategy": "v2",
            "plan_global_speed": 1.15,
            "deepseek_api_keys": "",
            "ffmpeg_path": "",
            "ffprobe_path": "",
            "video_download_dir": "",
            "video_download_auto_unzip": True,
            "video_download_auto_transcribe": True,
            "video_download_auto_plan": True,
            "video_download_auto_import_clip": True,
            "video_download_auto_start_after_add": True,
        },
        "Update": {
            "dismissed_version": "",
            "machine_info_reported_date": "",
        },
        "QFluentWidgets": {
            "FontFamilies": [
                "Segoe UI",
                "Microsoft YaHei",
                "PingFang SC",
            ],
            "ThemeColor": "#ff70d5f3",
            "ThemeMode": "Light",
        },
    }
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    dst = DIST_DIR / "config.json"
    dst.write_text(
        json.dumps(clean, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    print("Bundled clean default config.json (no credentials)")


def cleanup_dist() -> None:
    for name in CLEANUP_DIRS:
        path = DIST_DIR.joinpath(*name.split("/"))
        if path.is_dir():
            shutil.rmtree(path)
            print(f"Removed unused: {name}")
        elif path.is_file():
            path.unlink()
            print(f"Removed unused: {name}")

    # 清理残留的 Python 字节码、日志及诊断转储文件，保持 dist 纯净
    for pycache in list(DIST_DIR.rglob("__pycache__")):
        if pycache.is_dir():
            try:
                shutil.rmtree(pycache)
            except Exception:
                pass
    for ext in ("*.pyc", "*.pyo", "*.log", "*.aedump"):
        for f in list(DIST_DIR.rglob(ext)):
            if f.is_file():
                try:
                    f.unlink()
                except Exception:
                    pass
    for dirty_dir in (DIST_DIR / "logs", DIST_DIR / "changdu_data"):
        if dirty_dir.is_dir():
            try:
                shutil.rmtree(dirty_dir)
            except Exception:
                pass
    print("Cleaned up residual cache and temp files in dist")


def bundle_outro() -> None:
    src_dir = PROJECT_ROOT / "tools" / "outro"
    dst_dir = DIST_DIR / "tools" / "outro"
    if not src_dir.is_dir():
        print(f"Warning: {src_dir} not found, skipping outro bundle")
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    found = False
    for src in src_dir.glob("*.mp4"):
        dst = dst_dir / src.name
        try:
            if dst.is_file():
                try:
                    os.chmod(dst, 0o666)
                except Exception:
                    pass
            shutil.copy2(src, dst)
            print(f"Bundled outro {src.name}")
            found = True
        except OSError as exc:
            print(f"Warning: failed to bundle outro {src.name}: {exc}")
    if not found:
        print(f"Warning: no outro mp4 files in {src_dir}")


def bundle_overlay_fonts() -> None:
    """打包叠字/花字用的内置字体（tools/fonts）。"""
    src_dir = PROJECT_ROOT / "tools" / "fonts"
    dst_dir = DIST_DIR / "tools" / "fonts"
    if not src_dir.is_dir():
        print(f"Warning: {src_dir} not found, skipping overlay fonts bundle")
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    found = False
    for src in src_dir.iterdir():
        if not src.is_file():
            continue
        if src.suffix.lower() not in {".ttf", ".otf", ".ttc"}:
            continue
        dst = dst_dir / src.name
        try:
            shutil.copy2(src, dst)
            print(f"Bundled font {src.name}")
            found = True
        except OSError as exc:
            print(f"Warning: failed to bundle font {src.name}: {exc}")
    if not found:
        print(f"Warning: no font files in {src_dir}")


def bundle_vc_runtime() -> None:
    """用系统 VC++ 运行库替换 Nuitka 打包版本，避免 torch c10.dll 初始化失败。"""
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    for name in VC_RUNTIME_DLLS:
        dst = DIST_DIR / name
        if dst.exists():
            dst.unlink()
        src = system32 / name
        if src.is_file():
            shutil.copy2(src, dst)
            print(f"Bundled VC runtime: {name}")
        else:
            print(f"Warning: {name} not found in {system32}")


def _copy_site_package(name: str, *, label: str) -> None:
    """从 venv site-packages 拷贝目录包、单文件模块或 .pyd 扩展到 dist。"""
    # 通配符匹配（如 *__mypyc*.pyd）
    if "*" in name or "?" in name:
        matched = list(SITE_PACKAGES.glob(name))
        if not matched:
            print(f"Warning: {label} pattern {name} matched nothing in venv, skip copy")
            return
        for src in matched:
            dst = DIST_DIR / src.name
            shutil.copy2(src, dst)
            print(f"Copied {label}: {src.name}")
        return

    # 单文件模块/扩展：soundfile.py, typing_extensions.py, *.pyd
    if name.endswith(".py") or name.endswith(".pyd"):
        src = SITE_PACKAGES / name
        dst = DIST_DIR / name
        if not src.is_file():
            print(f"Warning: {label} {name} not found in venv, skip copy")
            return
        shutil.copy2(src, dst)
        print(f"Copied {label}: {name}")
        return

    # 优先匹配直接目录（如带点的 delvewheel 目录 llvmlite.libs 等）
    direct_src = SITE_PACKAGES / name
    if direct_src.is_dir():
        src = direct_src
        dst = DIST_DIR / name
    else:
        # 支持子包路径：torch.testing -> SITE_PACKAGES/torch/testing
        parts = name.split(".")
        src = SITE_PACKAGES.joinpath(*parts)
        dst = DIST_DIR.joinpath(*parts)

    if not src.is_dir():
        print(f"Warning: {label} {name} not found in venv, skip copy")
        return
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "test", "tests"),
    )
    print(f"Copied {label}: {name}")


def bundle_nofollow_packages() -> None:
    """将 nofollow 跳过的包以源码形式复制进 dist。"""
    if not SITE_PACKAGES.is_dir():
        print(f"Warning: site-packages not found at {SITE_PACKAGES}, skip nofollow copy")
        return
    for name in NOFOLLOW_COPY_PACKAGES:
        _copy_site_package(name, label="nofollow package")


def bundle_funasr_runtime_packages() -> None:
    """拷贝 FunASR 运行所需的传递依赖（nofollow 后 Nuitka 可能未收集）。"""
    if not SITE_PACKAGES.is_dir():
        print(f"Warning: site-packages not found at {SITE_PACKAGES}, skip ff deps copy")
        return
    for name in FUNASR_RUNTIME_COPY_PACKAGES:
        _copy_site_package(name, label="ff runtime dep")


def sync_app_layer() -> None:
    """将最新的资源与 app 业务代码增量同步到 dist。"""
    print("\n>>> [1/3] 编译最新的 UI 与 QRC 资源文件...")
    build_resources()

    print(">>> [2/3] 同步 app/ 业务代码与资源至 dist...")
    src_app = PROJECT_ROOT / "app"
    dst_app = DIST_DIR / "app"
    if dst_app.exists():
        shutil.rmtree(dst_app)
    shutil.copytree(
        src_app,
        dst_app,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    print("  -> 已同步: app/")

    rc_file = PROJECT_ROOT / "resource_rc.py"
    if rc_file.is_file():
        shutil.copy2(rc_file, DIST_DIR / "resource_rc.py")
        print("  -> 已同步: resource_rc.py")

    print(">>> [3/3] 同步配置与静态资源...")
    bundle_overlay_fonts()
    bundle_outro()
    bundle_ffmpeg()
    bundle_config()
    cleanup_dist()
    print("业务层装配完成！\n")


def _stdlib_lib_dir() -> Path:
    return Path(sys.base_prefix) / "Lib"


def _stdlib_dlls_dir() -> Path:
    return Path(sys.base_prefix) / "DLLs"


def _copy_stdlib_item(name: str, lib_dir: Path, dlls_dir: Path) -> None:
    src_py = lib_dir / f"{name}.py"
    src_pkg = lib_dir / name
    src_pyd = None
    if dlls_dir.is_dir():
        for candidate in dlls_dir.glob(f"{name}*.pyd"):
            src_pyd = candidate
            break
    if src_py.is_file():
        shutil.copy2(src_py, DIST_DIR / f"{name}.py")
        print(f"Copied stdlib module: {name}.py")
    elif src_pkg.is_dir():
        dst = DIST_DIR / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(
            src_pkg,
            dst,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "test", "tests"),
        )
        print(f"Copied stdlib package: {name}")
    elif src_pyd is not None:
        shutil.copy2(src_pyd, DIST_DIR / src_pyd.name)
        print(f"Copied stdlib extension: {src_pyd.name}")
    else:
        print(f"Warning: stdlib {name} not found under {lib_dir} or {dlls_dir}, skip")


def bundle_stdlib_modules() -> None:
    """拷贝 ASR 链路可能动态 import 的标准库模块到 dist。"""
    lib_dir = _stdlib_lib_dir()
    dlls_dir = _stdlib_dlls_dir()
    if not lib_dir.is_dir():
        print(f"Warning: stdlib Lib not found at {lib_dir}, skip stdlib copy")
        return
    for name in STDLIB_COPY_ITEMS:
        _copy_stdlib_item(name, lib_dir, dlls_dir)
    install_stdlib_bootstrap()


_STDLIB_BOOTSTRAP_MARKER = "import _ae_stdlib_bootstrap"
_STDLIB_BOOTSTRAP_SRC = PROJECT_ROOT / "scripts" / "ae_stdlib_bootstrap.py"


_CRITICAL_MODELS_MARKER = "# ae_critical_asr_models"
_CRITICAL_MODELS_FOOTER = """
# ae_critical_asr_models
def _ae_ensure_critical_asr_models():
    import traceback as _tb
    _log = os.path.join(os.path.dirname(os.path.dirname(__file__)), "funasr_import_debug.log")
    for _name in (
        "funasr.utils.load_utils",
        "funasr.frontends.wav_frontend",
        "funasr.tokenizer.sentencepiece_tokenizer",
        "funasr.models.sense_voice.model",
        "funasr.models.fsmn_vad_streaming.model",
        "funasr.models.paraformer.model",
        "funasr.models.bicif_paraformer.model",
    ):
        try:
            importlib.import_module(_name)
        except Exception as _e:
            _record_import_error(_name, _e)
            try:
                with open(_log, "a", encoding="utf-8") as _f:
                    _f.write(f"{_name}: {_e}\\n")
                    _f.write(_tb.format_exc() + "\\n")
            except Exception:
                pass

_ae_ensure_critical_asr_models()
"""


def install_stdlib_bootstrap() -> None:
    """在 dist 写入引导模块，并挂到 funasr 入口（无需重编 entry.exe 也能生效）。"""
    if not _STDLIB_BOOTSTRAP_SRC.is_file():
        print(f"Warning: {_STDLIB_BOOTSTRAP_SRC} missing, skip bootstrap")
        return
    bootstrap = DIST_DIR / "_ae_stdlib_bootstrap.py"
    shutil.copy2(_STDLIB_BOOTSTRAP_SRC, bootstrap)
    print(f"Wrote {bootstrap.name}")

    inject_targets = (
        DIST_DIR / "funasr" / "__init__.py",
        DIST_DIR / "modelscope" / "__init__.py",
    )
    header = (
        f"{_STDLIB_BOOTSTRAP_MARKER}\n"
        "_ae_stdlib_bootstrap.apply()\n"
    )
    for init_py in inject_targets:
        if not init_py.is_file():
            continue
        text = init_py.read_text(encoding="utf-8")
        if _STDLIB_BOOTSTRAP_MARKER not in text:
            text = header + text
            print(f"Injected stdlib bootstrap into {init_py.relative_to(DIST_DIR)}")
        if init_py.name == "__init__.py" and "funasr" in str(init_py.parent.name):
            if _CRITICAL_MODELS_MARKER not in text:
                text = text.rstrip() + "\n" + _CRITICAL_MODELS_FOOTER
                print("Injected critical ASR model ensure into funasr/__init__.py")
        init_py.write_text(text, encoding="utf-8")


def verify_bundled_dependencies() -> None:
    """打包后冒烟测试：验证 requests 依赖零警告、sentencepiece 原生扩展可用、ASR 组件注册表完整。"""
    print("Verifying bundled dependencies in dist...")

    # sentencepiece 必须保持 nofollow 源码形态，否则 Nuitka 编译版会遮蔽 _sentencepiece.pyd
    build_module_c = OUT_DIR / "entry.build" / "module.sentencepiece.c"
    if build_module_c.exists():
        sys.exit(
            "Bundled dependencies verification failed: sentencepiece 被 Nuitka 编译"
            f"（{build_module_c} 存在），原生扩展会被遮蔽，请检查 NUITKA_NOFOLLOW_MODULES。"
        )

    dist_literal = repr(str(DIST_DIR))
    test_code = (
        "import sys, os, glob, warnings\n"
        f"dist = {dist_literal}\n"
        "sys.path.insert(0, dist)\n"
        "pyd = glob.glob(os.path.join(dist, 'sentencepiece', '_sentencepiece*.pyd'))\n"
        "assert pyd, 'missing sentencepiece native extension _sentencepiece*.pyd'\n"
        "warnings.simplefilter('error')\n"
        "import charset_normalizer\n"
        "import requests\n"
        "warnings.resetwarnings()\n"
        "print('Dependency verification OK')\n"
        "_orig_path = list(sys.path)\n"
        "_orig_cwd = os.getcwd()\n"
        "sys.path = [p for p in sys.path if 'site-packages' not in p.lower()]\n"
        "os.chdir(dist)\n"
        "try:\n"
        "    os.add_dll_directory(dist)\n"
        "except Exception:\n"
        "    pass\n"
        "import sentencepiece\n"
        "assert hasattr(sentencepiece, 'SentencePieceProcessor'), 'SentencePieceProcessor missing'\n"
        "print('sentencepiece isolated import OK')\n"
        "import openai\n"
        "assert hasattr(openai, 'OpenAI'), 'openai.OpenAI missing'\n"
        "print('openai isolated import OK')\n"
        "import sympy\n"
        "assert hasattr(sympy, 'Symbol'), 'sympy.Symbol missing'\n"
        "print('sympy isolated import OK')\n"
        "sys.path[:] = _orig_path\n"
        "os.chdir(_orig_cwd)\n"
        "import importlib\n"
        "for _name in (\n"
        "    'funasr.utils.load_utils',\n"
        "    'funasr.frontends.wav_frontend',\n"
        "    'funasr.tokenizer.sentencepiece_tokenizer',\n"
        "    'funasr.models.sense_voice.model',\n"
        "    'funasr.models.fsmn_vad_streaming.model',\n"
        "):\n"
        "    importlib.import_module(_name)\n"
        "from funasr.register import tables\n"
        "required = {\n"
        "    'model_classes': ('SenseVoiceSmall', 'FsmnVADStreaming'),\n"
        "    'encoder_classes': ('SenseVoiceEncoderSmall', 'FSMN'),\n"
        "    'frontend_classes': ('WavFrontend', 'WavFrontendOnline'),\n"
        "    'tokenizer_classes': ('SentencepiecesTokenizer',),\n"
        "}\n"
        "missing = [\n"
        "    f'{_t}:{_k}'\n"
        "    for _t, _keys in required.items()\n"
        "    for _k in _keys\n"
        "    if _k not in getattr(tables, _t, {})\n"
        "]\n"
        "assert not missing, f'Missing ASR components: {missing}'\n"
        "print('ASR component registry verification OK')\n"
    )
    cmd = [sys.executable, "-c", test_code]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Dependency verification FAILED:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}")
        sys.exit(f"Bundled dependencies verification failed: {res.stderr.strip()}")
    print("Bundled dependencies verification passed: requests + sentencepiece + openai + sympy + ASR components OK.")


def find_iscc() -> Path | None:
    """查找 Inno Setup 编译器 ISCC.exe"""
    which_iscc = shutil.which("iscc")
    if which_iscc:
        return Path(which_iscc)

    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def build_installer(*, fast_pack: bool = False) -> None:
    """调用 Inno Setup 生成安装包，并写入 release/version.json。"""
    iscc_exe = find_iscc()
    if not iscc_exe:
        print("Warning: ISCC.exe not found. Please install Inno Setup 6 or add it to PATH.")
        return

    iss_file = PROJECT_ROOT / "scripts" / "pack_installer.iss"
    if not iss_file.is_file():
        print(f"Warning: {iss_file} not found, skip installer build")
        return

    level = "fast" if fast_pack else "max"
    print(f"\nBuilding installer with Inno Setup (compression level: {level})...")
    cmd = f'"{iscc_exe}" /DCompressionLevel={level} "{iss_file}"'
    if run_cmd(cmd) != 0:
        sys.exit("Failed to build installer with Inno Setup")

    # 写入 release/version.json
    version_script = PROJECT_ROOT / "scripts" / "write_release_version.py"
    if version_script.is_file():
        run_cmd(f'"{sys.executable}" "{version_script}"')


def main():
    parser = argparse.ArgumentParser(description="Build script for Windows")
    parser.add_argument("--quick-test", action="store_true", help="Skip Nuitka build and use dummy files")
    parser.add_argument("--installer", action="store_true", help="Build Inno Setup installer after build")
    parser.add_argument(
        "--fast-pack",
        action="store_true",
        help="Use lzma2/fast for fast packaging (implies --installer; saves time during testing)",
    )
    parser.add_argument(
        "--app-only",
        "--patch",
        action="store_true",
        help="快速打包：跳过 Nuitka 编译，直接复用已有底座，同步 app/ 业务代码和资源到 dist 并生成安装包（16秒极速出包）",
    )
    args = parser.parse_args()

    _warn_if_non_ascii_path()

    if args.app_only:
        exe_path = DIST_DIR / "entry.exe"
        if not exe_path.is_file():
            sys.exit(
                "错误：未找到 out/entry.dist/entry.exe 底座！\n"
                "首次构建必须先生成底座：uv run python scripts/build.py --installer"
            )
        t0 = time.perf_counter()
        print("\n>>> 正在以 --app-only 极速模式装配业务层 (app/ + 资源)...")
        sync_app_layer()
        if args.installer or args.fast_pack:
            build_installer(fast_pack=args.fast_pack)
        elapsed = time.perf_counter() - t0
        print(f"\n[OK] 极速打包完成！全流程总用时: {elapsed:.2f} 秒")
        return

    build_resources()

    if not args.quick_test:
        build_command = f'"{sys.executable}" -m nuitka --standalone --mingw64 --enable-plugin=pyside6 '
        build_command += "--assume-yes-for-downloads "
        build_command += "--windows-console-mode=disable "
        build_command += "--windows-icon-from-ico=resource/images/logo.ico "
        build_command += f"--output-dir=out "
        build_command += f"--windows-company-name={AUTHOR} --windows-product-name={APP_NAME} "
        build_command += f"--windows-product-version={VERSION} "
        build_command += "--follow-import-to=app "
        build_command += "--module-parameter=torch-disable-jit=yes "
        build_command += "--noinclude-numba-mode=nofollow "
        # 提速配置：
        # 1. 禁用 MinGW LTO 链接优化，避免全程序跨模块重分析导致链接卡顿 5~10 分钟
        build_command += "--lto=no "
        # 2. 跑满系统所有 CPU 核心
        cpu_jobs = os.cpu_count() or 8
        build_command += f"--jobs={cpu_jobs} "
        # 3. 跳过第三方依赖内部大量无用测试模块的代码生成与编译
        build_command += "--nofollow-import-to=*.tests "
        build_command += "--nofollow-import-to=*.test "
        # 4. 跳过第三方库中的 .pyi 类型存根文件扫描
        build_command += "--no-pyi-file "
        for module in NUITKA_NOFOLLOW_MODULES:
            build_command += f"--nofollow-import-to={module} "
        for module in STDLIB_INCLUDE_MODULES:
            build_command += f"--include-module={module} "
        build_command += "entry.py"

        if run_cmd(build_command) != 0:
            sys.exit("Nuitka build failed")
        bundle_nofollow_packages()
        bundle_funasr_runtime_packages()
        bundle_stdlib_modules()
    else:
        print("Skipping Nuitka build (--quick-test)")
        DIST_DIR.mkdir(parents=True, exist_ok=True)
        exe_path = DIST_DIR / "entry.exe"
        if not exe_path.exists():
            exe_path.write_text("Dummy executable")
        bundle_nofollow_packages()
        bundle_funasr_runtime_packages()
        bundle_stdlib_modules()

    useless_dlls = []
    for dll in useless_dlls:
        file_path = DIST_DIR / dll
        if file_path.exists():
            print(f"Removing {dll}")
            file_path.unlink()

    bundle_vc_runtime()
    bundle_ffmpeg()
    bundle_outro()
    bundle_overlay_fonts()
    bundle_playwright_browsers()
    bundle_config()
    cleanup_dist()
    sync_app_layer()
    verify_bundled_dependencies()
    print("Build success")

    if args.installer or args.fast_pack:
        build_installer(fast_pack=args.fast_pack)


if __name__ == "__main__":
    main()
