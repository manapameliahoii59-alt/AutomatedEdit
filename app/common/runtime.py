"""运行环境判断（开发源码 vs 打包发布）。"""

from __future__ import annotations

import sys


def is_dev_runtime() -> bool:
    """源码/开发运行时为 True；Nuitka、PyInstaller 等打包后为 False。"""
    if getattr(sys, "frozen", False):
        return False
    main = sys.modules.get("__main__")
    if main is not None and getattr(main, "__compiled__", False):
        return False
    return True
