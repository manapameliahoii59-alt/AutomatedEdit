import argparse
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# Try to import config, handle missing dependencies gracefully for build script if possible,
# but since we need VERSION and AUTHOR, we assume dependencies are there.
try:
    from common.config import VERSION, AUTHOR
except ImportError:
    print("Warning: Could not import common.config. Using default values.")
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
    if run_cmd(f"{sys.executable} pack_resources.py") != 0:
        sys.exit("Failed to build resources")

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
        build_command += "--follow-import-to=app,common,components "
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

    print("Build success")

if __name__ == "__main__":
    main()
