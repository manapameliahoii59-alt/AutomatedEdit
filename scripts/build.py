import argparse
import os
import shutil
import subprocess
import sys
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
    # torch 子包中使用 walrus 操作符等语法，Nuitka 无法稳定编译
    "torch._dynamo",
    "torch._inductor",
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

    # 只打包当前 Playwright 版本所需的 Chromium（含 headless shell）
    keep = {"chromium-1228", "chromium_headless_shell-1228", "ffmpeg-1011", "winldd-1007"}
    for browser_dir in local_browsers.iterdir():
        if not browser_dir.is_dir() or browser_dir.name not in keep:
            continue
        dst = dst_base / browser_dir.name
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
        },
        "LLM": {
            "dashscope_api_key": "",
        },
        "Tools": {
            "changdu_email": "",
            "changdu_password": "",
            "clip_export_dir": "",
            "clip_export_name_tag": "",
            "clip_last_import_dir": "",
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
            shutil.copy2(src, dst)
            print(f"Bundled outro {src.name}")
            found = True
        except OSError as exc:
            print(f"Warning: failed to bundle outro {src.name}: {exc}")
    if not found:
        print(f"Warning: no outro mp4 files in {src_dir}")


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
    """从 venv site-packages 拷贝目录包或单文件模块到 dist。"""
    # 单文件模块：soundfile.py
    if name.endswith(".py"):
        src = SITE_PACKAGES / name
        dst = DIST_DIR / name
        if not src.is_file():
            print(f"Warning: {label} {name} not found in venv, skip copy")
            return
        shutil.copy2(src, dst)
        print(f"Copied {label}: {name}")
        return

    # 支持子包路径：torch.testing -> SITE_PACKAGES/torch/testing
    parts = name.split(".")
    src = SITE_PACKAGES.joinpath(*parts)
    if not src.is_dir():
        print(f"Warning: {label} {name} not found in venv, skip copy")
        return
    dst = DIST_DIR.joinpath(*parts)
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst)
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


def main():
    parser = argparse.ArgumentParser(description="Build script for Windows")
    parser.add_argument("--quick-test", action="store_true", help="Skip Nuitka build and use dummy files")
    args = parser.parse_args()

    _warn_if_non_ascii_path()
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
    bundle_playwright_browsers()
    bundle_config()
    cleanup_dist()
    print("Build success")


if __name__ == "__main__":
    main()
