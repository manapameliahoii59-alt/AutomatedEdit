"""根据当前 VERSION 写入 release/version.json（与安装包同目录）。

用法（打包安装包后执行）:
  iscc scripts/pack_installer.iss
  uv run python scripts/write_release_version.py
  uv run python scripts/write_release_version.py --changelog "修复若干问题"
  uv run python scripts/write_release_version.py --min-supported 0.0.1
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.common.config import APP_NAME, VERSION  # noqa: E402


def write_release_version(
    *,
    changelog: str = "",
    min_supported: str | None = None,
    release_dir: Path | None = None,
) -> Path:
    out_dir = release_dir or (ROOT / "release")
    out_dir.mkdir(parents=True, exist_ok=True)
    installer = f"{APP_NAME}-v{VERSION}-installer.exe"
    payload = {
        "latest": VERSION,
        "min_supported": (min_supported or VERSION).strip() or VERSION,
        "installer": installer,
        "changelog": changelog.strip(),
    }
    path = out_dir / "version.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="写入 release/version.json")
    parser.add_argument("--changelog", default="", help="更新说明")
    parser.add_argument(
        "--min-supported",
        default=None,
        help="最低支持版本（默认与当前 VERSION 相同）",
    )
    args = parser.parse_args()
    path = write_release_version(
        changelog=args.changelog,
        min_supported=args.min_supported,
    )
    print(f"已写入 {path}")
    print(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
