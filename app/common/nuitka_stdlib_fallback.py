"""Nuitka 打包后，已冻结的标准库包往往缺少子模块（如 logging.config）。

把 dist 目录里拷贝的标准库包路径注入到已加载包的 __path__，
或从磁盘直接加载子模块，供 FunASR / ModelScope 动态 import。
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import os
import sys


def _dist_root() -> str:
    # Nuitka standalone：可执行文件所在目录
    if "__compiled__" in globals() or getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    # 开发模式：项目根（entry.py 所在目录）
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _ensure_package_path(pkg_name: str, root: str) -> None:
    pkg = sys.modules.get(pkg_name)
    if pkg is None:
        return
    pkg_dir = os.path.join(root, *pkg_name.split("."))
    if not os.path.isdir(pkg_dir):
        return
    paths = list(getattr(pkg, "__path__", []))
    if pkg_dir not in paths:
        try:
            pkg.__path__ = [pkg_dir, *paths]  # type: ignore[attr-defined]
        except Exception:
            pass


def _load_module_from_file(fullname: str, file_path: str):
    spec = importlib.util.spec_from_file_location(fullname, file_path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[fullname] = module
    spec.loader.exec_module(module)
    return module


def ensure_stdlib_submodule(fullname: str, root: str | None = None) -> bool:
    """确保 fullname（如 logging.config）可 import。成功返回 True。"""
    if fullname in sys.modules:
        return True
    try:
        importlib.import_module(fullname)
        return True
    except ModuleNotFoundError:
        pass

    root = root or _dist_root()
    parts = fullname.split(".")
    if len(parts) < 2:
        return False

    # 先把父包 __path__ 指到 dist 里的拷贝
    for i in range(1, len(parts)):
        _ensure_package_path(".".join(parts[:i]), root)

    try:
        importlib.import_module(fullname)
        return True
    except ModuleNotFoundError:
        pass

    file_path = os.path.join(root, *parts) + ".py"
    init_path = os.path.join(root, *parts, "__init__.py")
    if os.path.isfile(file_path):
        return _load_module_from_file(fullname, file_path) is not None
    if os.path.isfile(init_path):
        return _load_module_from_file(fullname, init_path) is not None
    return False


# FunASR 链路里已踩过/易踩的标准库子模块
_CRITICAL_STDLIB_SUBMODULES = (
    "logging.config",
    "logging.handlers",
    "concurrent.futures",
    "xml.etree.ElementTree",
)


def ensure_distutils() -> None:
    """Python 3.12+ 无内置 distutils；FunASR 依赖 distutils.version.LooseVersion。"""
    try:
        from distutils.version import LooseVersion  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    root = _dist_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        import setuptools._distutils as _du

        sys.modules.setdefault("distutils", _du)
        for sub in ("version", "util", "spawn", "errors", "sysconfig"):
            try:
                mod = importlib.import_module(f"setuptools._distutils.{sub}")
                sys.modules.setdefault(f"distutils.{sub}", mod)
            except Exception:
                pass
    except Exception:
        pass


def apply_nuitka_stdlib_fallback() -> None:
    root = _dist_root()
    # 常见顶层包：若已在 sys.modules，补上磁盘路径
    for name in ("logging", "concurrent", "xml", "html", "http", "urllib", "email", "sqlite3", "zoneinfo"):
        _ensure_package_path(name, root)
    for fullname in _CRITICAL_STDLIB_SUBMODULES:
        ensure_stdlib_submodule(fullname, root)
    ensure_distutils()


class DistStdlibMetaPathFinder(importlib.abc.MetaPathFinder):
    """运行期兜底：任意缺失模块若在 dist 根目录有对应 .py/包则从磁盘加载。"""

    def __init__(self, root: str | None = None):
        self._root = root or _dist_root()

    def find_spec(self, fullname, path, target=None):
        parts = fullname.split(".")
        if not parts:
            return None
        for i in range(1, len(parts)):
            _ensure_package_path(".".join(parts[:i]), self._root)
        py_path = os.path.join(self._root, *parts) + ".py"
        pkg_init = os.path.join(self._root, *parts, "__init__.py")
        if not (os.path.isfile(py_path) or os.path.isfile(pkg_init)):
            return None
        search = [os.path.join(self._root, *parts[:-1])] if len(parts) > 1 else [self._root]
        parent = sys.modules.get(".".join(parts[:-1])) if len(parts) > 1 else None
        if parent is not None and hasattr(parent, "__path__"):
            search = list(parent.__path__)
        return importlib.machinery.PathFinder.find_spec(fullname, search, target)


def install_dist_stdlib_importer() -> None:
    root = _dist_root()
    # 避免重复安装
    for finder in sys.meta_path:
        if isinstance(finder, DistStdlibMetaPathFinder):
            return
    sys.meta_path.insert(0, DistStdlibMetaPathFinder(root))
    apply_nuitka_stdlib_fallback()
