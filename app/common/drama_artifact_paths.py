"""剧目识别/策划产物路径：开发环境放剧目根目录，正式环境放隐藏子目录。"""

from __future__ import annotations

import os
import sys

from app.common.runtime import is_dev_runtime

ARTIFACT_DIR_NAME = ".automatededit"
SCRIPT_DATA_FILENAME = "full_script_data.json"
PRODUCTION_PLAN_FILENAME = "production_plan_v3.json"

# 升级前写在剧目根目录的路径（只读兼容）
LEGACY_SCRIPT_DATA_FILENAME = SCRIPT_DATA_FILENAME
LEGACY_PRODUCTION_PLAN_FILENAME = PRODUCTION_PLAN_FILENAME


def use_hidden_artifact_dir() -> bool:
    """正式/打包环境为 True，开发源码环境为 False。"""
    return not is_dev_runtime()


def artifact_dir(project_path: str) -> str:
    return os.path.join(project_path, ARTIFACT_DIR_NAME)


def _legacy_script_path(project_path: str) -> str:
    return os.path.join(project_path, LEGACY_SCRIPT_DATA_FILENAME)


def _legacy_plan_path(project_path: str) -> str:
    return os.path.join(project_path, LEGACY_PRODUCTION_PLAN_FILENAME)


def script_data_write_path(project_path: str) -> str:
    """当前环境应写入的识别产物路径。"""
    if use_hidden_artifact_dir():
        return os.path.join(artifact_dir(project_path), SCRIPT_DATA_FILENAME)
    return _legacy_script_path(project_path)


def production_plan_write_path(project_path: str) -> str:
    """当前环境应写入的策划产物路径。"""
    if use_hidden_artifact_dir():
        return os.path.join(artifact_dir(project_path), PRODUCTION_PLAN_FILENAME)
    return _legacy_plan_path(project_path)


def locate_script_data(project_path: str) -> str | None:
    """查找已存在的识别产物（优先正式路径，再兼容旧路径）。"""
    candidates = [script_data_write_path(project_path), _legacy_script_path(project_path)]
    seen: set[str] = set()
    for path in candidates:
        norm = os.path.normpath(path)
        if norm in seen:
            continue
        seen.add(norm)
        if os.path.isfile(path):
            return path
    return None


def locate_production_plan(project_path: str) -> str | None:
    """查找已存在的策划产物（优先正式路径，再兼容旧路径）。"""
    candidates = [production_plan_write_path(project_path), _legacy_plan_path(project_path)]
    seen: set[str] = set()
    for path in candidates:
        norm = os.path.normpath(path)
        if norm in seen:
            continue
        seen.add(norm)
        if os.path.isfile(path):
            return path
    return None


def ensure_artifact_dir(project_path: str) -> None:
    """正式环境写入前创建隐藏目录。"""
    if not use_hidden_artifact_dir():
        return
    os.makedirs(artifact_dir(project_path), exist_ok=True)
    _set_hidden(artifact_dir(project_path))


def prepare_write_path(project_path: str, *, script: bool) -> str:
    """返回写入路径并确保父目录存在；正式环境会先解除旧产物的隐藏属性以便覆盖写入。"""
    ensure_artifact_dir(project_path)
    if script:
        path = script_data_write_path(project_path)
    else:
        path = production_plan_write_path(project_path)
    # Windows 上对已设 Hidden 的文件直接 open(..., "w") 常报 Errno 13
    ensure_path_writable(path)
    return path


def ensure_path_writable(path: str) -> None:
    """写入前清除 Hidden/ReadOnly，避免覆盖正式环境隐藏产物时 Permission denied。"""
    if not path or not os.path.exists(path):
        return
    if sys.platform != "win32":
        # 非 Windows：尽量去掉只读位
        try:
            mode = os.stat(path).st_mode
            os.chmod(path, mode | 0o200)
        except OSError:
            pass
        return
    try:
        import ctypes

        FILE_ATTRIBUTE_NORMAL = 0x80
        ctypes.windll.kernel32.SetFileAttributesW(
            os.path.normpath(path), FILE_ATTRIBUTE_NORMAL
        )
    except Exception:
        pass


def finalize_written_artifact(filepath: str) -> None:
    """正式环境写入后为文件（及目录）设置隐藏属性。"""
    if not use_hidden_artifact_dir():
        return
    _set_hidden(filepath)
    _set_hidden(os.path.dirname(filepath))


def _set_hidden(path: str) -> None:
    if not path or not os.path.exists(path):
        return
    if sys.platform != "win32":
        return
    try:
        import ctypes

        FILE_ATTRIBUTE_HIDDEN = 0x02
        ctypes.windll.kernel32.SetFileAttributesW(os.path.normpath(path), FILE_ATTRIBUTE_HIDDEN)
    except Exception:
        pass
