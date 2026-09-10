import builtins
import os
import sys


def is_dev_runtime() -> bool:
    """源码/开发运行时为 True；Nuitka、PyInstaller 等打包后为 False。"""
    force_dev = os.environ.get("AE_FORCE_DEV_ERROR", "").strip().lower() in {"1", "true", "yes", "on"}
    force_prod = os.environ.get("AE_FORCE_PROD_ERROR", "").strip().lower() in {"1", "true", "yes", "on"}
    if force_dev:
        return True
    if force_prod:
        return False
    if getattr(sys, "frozen", False):
        return False
    if getattr(builtins, "__compiled__", False):
        return False
    main = sys.modules.get("__main__")
    if main is not None and getattr(main, "__compiled__", False):
        return False
    return True
