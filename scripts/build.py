import argparse
import os
import shutil
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

def run_cmd(cmd: str) -> int:
    print(f"Run cmd: {cmd}")
    return os.system(cmd)

def build_resources() -> None:
    """Run pack_resources.py"""
    print("Building resources...")
    if run_cmd(f"{sys.executable} scripts/pack_resources.py") != 0:
        sys.exit("Failed to build resources")

def bundle_ffmpeg() -> None:
    src_dir = PROJECT_ROOT / "tools" / "ffmpeg" / "win"
    if not (src_dir / "ffmpeg.exe").is_file():
        env_src = os.environ.get("FFMPEG_SOURCE_DIR")
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


def bundle_outro() -> None:
    src_dir = PROJECT_ROOT / "tools" / "outro"
    dst_dir = DIST_DIR / "tools" / "outro"
    if not src_dir.is_dir():
        print(f"Warning: {src_dir} not found, skipping outro bundle")
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    found = False
    for src in src_dir.glob("*.mp4"):
        shutil.copy2(src, dst_dir / src.name)
        print(f"Bundled outro {src.name}")
        found = True
    if not found:
        print(f"Warning: no outro mp4 files in {src_dir}")


def main():
    parser = argparse.ArgumentParser(description="Build script for Windows")
    parser.add_argument("--quick-test", action="store_true", help="Skip Nuitka build and use dummy files")
    args = parser.parse_args()

    # Build resources first
    build_resources()

    if not args.quick_test:
        build_command = "nuitka --standalone --mingw64 --enable-plugin=pyside6 "
        build_command += "--assume-yes-for-downloads "
        build_command += "--windows-console-mode=disable "
        build_command += "--windows-icon-from-ico=resource/images/logo.png "
        build_command += f"--output-dir=out "
        build_command += f"--windows-company-name={AUTHOR} --windows-product-name={APP_NAME} "
        build_command += f"--windows-product-version={VERSION} "
        build_command += "--follow-import-to=app "
        build_command += "entry.py"

        if run_cmd(build_command) != 0:
            sys.exit("Nuitka build failed")
    else:
        print("Skipping Nuitka build (--quick-test)")
        DIST_DIR.mkdir(parents=True, exist_ok=True)
        exe_path = DIST_DIR / "entry.exe"
        if not exe_path.exists():
             exe_path.write_text("Dummy executable")

    # Clean useless DLLs
    # 这里填写不需要的dll文件，打包后会自动删除
    useless_dlls = []
    
    for dll in useless_dlls:
        file_path = DIST_DIR / dll
        if file_path.exists():
            print(f"Removing {dll}")
            file_path.unlink()

    bundle_ffmpeg()
    bundle_outro()
    print("Build success")

if __name__ == "__main__":
    main()
