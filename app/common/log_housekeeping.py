"""本地崩溃 / 运行日志清理，避免长期使用后无限膨胀。

策略：
- 体积兜底（每次启动）：对 crash.log / funasr_import_debug.log 等在单文件超过
  上限时只保留尾部若干字节；
- 每日一次：删除 logs/ 目录下超过保留天数的历史日志（含 loguru 轮转文件）。

仅依赖标准库，必须在 entry.py 重定向 stderr 之前调用。
"""

from __future__ import annotations

import os
import time
from datetime import date

RETENTION_DAYS = 7
MAX_CRASH_LOG_BYTES = 10 * 1024 * 1024
CRASH_LOG_KEEP_BYTES = 1024 * 1024
_MARKER_NAME = ".log_housekeeping"
_TRIMMED_FILES = ("crash.log", "funasr_import_debug.log")


def _trim_file(path: str, max_bytes: int, keep_bytes: int) -> None:
    """超过 max_bytes 时只保留尾部 keep_bytes，避免单文件无限增长。"""
    try:
        size = os.path.getsize(path)
    except OSError:
        return
    if size <= max_bytes:
        return
    try:
        with open(path, "rb") as f:
            f.seek(max(0, size - keep_bytes))
            tail = f.read()
        with open(path, "wb") as f:
            f.write(tail)
    except OSError:
        pass


def _delete_old_files(directory: str, retention_days: int) -> None:
    cutoff = time.time() - retention_days * 86400
    try:
        names = os.listdir(directory)
    except OSError:
        return
    for name in names:
        path = os.path.join(directory, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            continue


def _read_marker(marker: str) -> str:
    try:
        with open(marker, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _write_marker(marker: str, value: str) -> None:
    try:
        with open(marker, "w", encoding="utf-8") as f:
            f.write(value)
    except OSError:
        pass


def run_daily_log_cleanup(
    app_dir: str,
    *,
    logs_dir: str | None = None,
    retention_days: int = RETENTION_DAYS,
    max_crash_bytes: int = MAX_CRASH_LOG_BYTES,
    keep_bytes: int = CRASH_LOG_KEEP_BYTES,
    force: bool = False,
) -> bool:
    """清理本地日志。

    返回本次是否执行了每日清理（体积裁剪每次启动都会执行）。
    """
    app_dir = os.path.abspath(app_dir)
    logs_dir = logs_dir or os.path.join(app_dir, "logs")
    marker = os.path.join(app_dir, _MARKER_NAME)

    # 体积兜底：单文件过大时保留尾部
    for name in _TRIMMED_FILES:
        _trim_file(os.path.join(app_dir, name), max_crash_bytes, keep_bytes)

    today = date.today().isoformat()
    if not force and _read_marker(marker) == today:
        return False

    _delete_old_files(logs_dir, retention_days)
    _write_marker(marker, today)
    return True
