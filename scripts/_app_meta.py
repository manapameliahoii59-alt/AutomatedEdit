"""从 app/common/config.py 读取打包用的常量。

打包/发布脚本只需要 APP_NAME 与 VERSION，直接 import app.common.config 会连带
拉起 PySide6、qfluentwidgets 等运行时依赖，在纯命令行环境下过重甚至不可用，
因此这里用正则读取模块顶层的常量赋值。
"""

from __future__ import annotations

import re
from pathlib import Path

CONFIG_FILE = Path(__file__).resolve().parents[1] / "app" / "common" / "config.py"


def _read_constant(name: str) -> str:
    text = CONFIG_FILE.read_text(encoding="utf-8")
    match = re.search(
        rf"^{name}\s*=\s*(['\"])(.*?)\1\s*$",
        text,
        flags=re.MULTILINE,
    )
    if not match:
        raise RuntimeError(f"未能在 {CONFIG_FILE} 中找到常量 {name}")
    return match.group(2)


def read_app_meta() -> tuple[str, str]:
    """返回 (APP_NAME, VERSION)。"""
    return _read_constant("APP_NAME"), _read_constant("VERSION")


APP_NAME, VERSION = read_app_meta()
