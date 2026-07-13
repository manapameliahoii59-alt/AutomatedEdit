"""诊断 out/entry.dist/entry.exe 启动失败原因（捕获 stderr/stdout）。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_DIR = PROJECT_ROOT / "out" / "entry.dist"
EXE = DIST_DIR / "entry.exe"
LOG = DIST_DIR / "diagnose_run.txt"


def main() -> int:
    if not EXE.is_file():
        print(f"未找到: {EXE}")
        return 1

    print(f"运行: {EXE}")
    print(f"输出写入: {LOG}")
    with LOG.open("w", encoding="utf-8", errors="replace") as fh:
        proc = subprocess.run(
            [str(EXE)],
            cwd=str(DIST_DIR),
            stdout=fh,
            stderr=subprocess.STDOUT,
            check=False,
        )

    text = LOG.read_text(encoding="utf-8", errors="replace").strip()
    if text:
        print("--- 程序输出 ---")
        print(text)
    else:
        print("（无控制台输出，可能是 native DLL 崩溃或未写 stderr）")

    print(f"--- 退出码: {proc.returncode} ---")
    logs_dir = DIST_DIR / "logs"
    if logs_dir.is_dir():
        print(f"已生成日志目录: {logs_dir}")
    else:
        print("未生成 logs/，崩溃可能发生在 logger 初始化之前")

    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
