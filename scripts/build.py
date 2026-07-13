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
    from app.common.config import VERSION, AUTHOR
except ImportError:
    print("Warning: Could not import app.common.config. Using default values.")
    VERSION = "1.0.0"
    AUTHOR = "Unknown"

APP_NAME = 'MyApp'
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

# nofollow 后需原样拷贝到 dist 的包目录名
NOFOLLOW_COPY_PACKAGES = (
    "transformers",
    "modelscope",
    "torch._dynamo",
    "torch._inductor",
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


def bundle_config() -> None:
    src = PROJECT_ROOT / "config.json"
    dst = DIST_DIR / "config.json"
    if src.is_file():
        shutil.copy2(src, dst)
        print(f"Bundled config.json")
    else:
        print("Warning: config.json not found in project root, skipping")


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


def bundle_nofollow_packages() -> None:
    """将 nofollow 跳过的包以源码形式复制进 dist。"""
    if not SITE_PACKAGES.is_dir():
        print(f"Warning: site-packages not found at {SITE_PACKAGES}, skip nofollow copy")
        return
    for name in NOFOLLOW_COPY_PACKAGES:
        # 支持子包路径：torch.testing -> SITE_PACKAGES/torch/testing
        parts = name.split(".")
        src = SITE_PACKAGES.joinpath(*parts)
        if not src.is_dir():
            print(f"Warning: package {name} not found in venv, skip copy")
            continue
        dst = DIST_DIR.joinpath(*parts)
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst)
        print(f"Copied nofollow package: {name}")


def main():
    parser = argparse.ArgumentParser(description="Build script for Windows")
    parser.add_argument("--quick-test", action="store_true", help="Skip Nuitka build and use dummy files")
    args = parser.parse_args()

    _warn_if_non_ascii_path()
    build_resources()

    if not args.quick_test:
        build_command = "nuitka --standalone --mingw64 --enable-plugin=pyside6 "
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
        build_command += "entry.py"

        if run_cmd(build_command) != 0:
            sys.exit("Nuitka build failed")
        bundle_nofollow_packages()
    else:
        print("Skipping Nuitka build (--quick-test)")
        DIST_DIR.mkdir(parents=True, exist_ok=True)
        exe_path = DIST_DIR / "entry.exe"
        if not exe_path.exists():
            exe_path.write_text("Dummy executable")

    useless_dlls = []
    for dll in useless_dlls:
        file_path = DIST_DIR / dll
        if file_path.exists():
            print(f"Removing {dll}")
            file_path.unlink()

    bundle_vc_runtime()
    bundle_ffmpeg()
    bundle_outro()
    bundle_config()
    print("Build success")


if __name__ == "__main__":
    main()
