"""Windows 下静默启动子进程，避免弹出黑框。"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

# 0x08000000 = CREATE_NO_WINDOW
_CREATE_NO_WINDOW = 0x08000000
_PATCHED = False


def subprocess_kwargs(**extra: Any) -> dict[str, Any]:
    """合并进 subprocess.run / Popen 的跨平台参数。"""
    kwargs: dict[str, Any] = dict(extra)
    if sys.platform == "win32":
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | _CREATE_NO_WINDOW
    return kwargs


def run(cmd, **kwargs):
    return subprocess.run(cmd, **subprocess_kwargs(**kwargs))


def popen(cmd, **kwargs):
    return subprocess.Popen(cmd, **subprocess_kwargs(**kwargs))


def install_silent_subprocess() -> None:
    """全局给 subprocess.Popen 加上 CREATE_NO_WINDOW。

    FunASR / ModelScope 等第三方会直接 subprocess.run/check_output 调 ffmpeg，
    不经过本模块的 run/popen；只改 Popen 即可覆盖这些路径。
    """
    global _PATCHED
    if _PATCHED or sys.platform != "win32":
        return
    _PATCHED = True

    _orig_popen = subprocess.Popen

    class _SilentPopen(_orig_popen):  # type: ignore[misc,valid-type]
        def __init__(self, *args, **kwargs):
            kwargs["creationflags"] = kwargs.get("creationflags", 0) | _CREATE_NO_WINDOW
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
