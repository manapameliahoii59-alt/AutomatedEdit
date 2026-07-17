"""Nuitka dist 标准库子模块回退（由 scripts/build.py 拷贝到 entry.dist）。"""
from __future__ import annotations

import importlib
import importlib.util
import os
import sys


def _root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _ensure_pkg_path(pkg_name: str, root: str) -> None:
    pkg = sys.modules.get(pkg_name)
    if pkg is None:
        return
    pkg_dir = os.path.join(root, *pkg_name.split("."))
    if not os.path.isdir(pkg_dir):
        return
    paths = list(getattr(pkg, "__path__", []))
    if pkg_dir not in paths:
        try:
            pkg.__path__ = [pkg_dir, *paths]
        except Exception:
            pass


def _load(fullname: str, file_path: str, package=None):
    if fullname in sys.modules:
        return sys.modules[fullname]
    spec = importlib.util.spec_from_file_location(fullname, file_path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    if package is not None:
        mod.__package__ = package
    sys.modules[fullname] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(fullname, None)
        raise
    return mod


def ensure(fullname: str) -> None:
    if fullname in sys.modules:
        return
    try:
        importlib.import_module(fullname)
        return
    except ModuleNotFoundError:
        pass
    except Exception:
        sys.modules.pop(fullname, None)

    root = _root()
    parts = fullname.split(".")
    for i in range(1, len(parts)):
        _ensure_pkg_path(".".join(parts[:i]), root)

    try:
        importlib.import_module(fullname)
        return
    except ModuleNotFoundError:
        pass
    except Exception:
        sys.modules.pop(fullname, None)

    py_path = os.path.join(root, *parts) + ".py"
    if os.path.isfile(py_path):
        parent = ".".join(parts[:-1])
        _load(fullname, py_path, package=parent)


def ensure_distutils() -> None:
    """Python 3.12+ 无内置 distutils；FunASR 多处 `from distutils.version import LooseVersion`。"""
    try:
        from distutils.version import LooseVersion  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    root = _root()
    if root not in sys.path:
        sys.path.insert(0, root)

    try:
        import setuptools._distutils as _du

        sys.modules.setdefault("distutils", _du)
        for sub in (
            "version",
            "util",
            "spawn",
            "errors",
            "sysconfig",
            "file_util",
            "dir_util",
            "log",
            "fancy_getopt",
            "cmd",
            "core",
            "dist",
        ):
            try:
                mod = importlib.import_module(f"setuptools._distutils.{sub}")
                sys.modules.setdefault(f"distutils.{sub}", mod)
            except Exception:
                pass
        from distutils.version import LooseVersion  # noqa: F401
    except Exception:
        pass


def install_silent_subprocess() -> None:
    """FunASR 调 ffmpeg 抽音频时会弹 CMD；在 import 第三方前全局静默 Popen。"""
    if sys.platform != "win32":
        return
    if getattr(install_silent_subprocess, "_done", False):
        return
    install_silent_subprocess._done = True  # type: ignore[attr-defined]
    try:
        import subprocess

        create_no_window = 0x08000000
        _orig_popen = subprocess.Popen

        class _SilentPopen(_orig_popen):  # type: ignore[misc,valid-type]
            def __init__(self, *args, **kwargs):
                kwargs["creationflags"] = kwargs.get("creationflags", 0) | create_no_window
                try:
                    if kwargs.get("startupinfo") is None and hasattr(subprocess, "STARTUPINFO"):
                        si = subprocess.STARTUPINFO()
                        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        si.wShowWindow = subprocess.SW_HIDE
                        kwargs["startupinfo"] = si
                except Exception:
                    pass
                super().__init__(*args, **kwargs)

        subprocess.Popen = _SilentPopen  # type: ignore[misc,assignment]
    except Exception:
        pass


def apply() -> None:
    try:
        install_silent_subprocess()
        root = _root()
        for name in (
            "logging",
            "concurrent",
            "xml",
            "html",
            "http",
            "urllib",
            "email",
            "sqlite3",
            "zoneinfo",
        ):
            _ensure_pkg_path(name, root)
        for fullname in (
            "logging.handlers",
            "logging.config",
            "concurrent.futures",
            "xml.etree",
            "xml.etree.ElementTree",
        ):
            try:
                ensure(fullname)
            except Exception:
                pass
        ensure_distutils()
    except Exception:
        pass
