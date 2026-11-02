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
    download_url: str | None = None,
    release_dir: Path | None = None,
) -> Path:
    out_dir = release_dir or (ROOT / "release")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "version.json"
    existing_min = ""
    existing_download_url = ""
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            existing_min = str(data.get("min_supported") or "").strip()
            existing_download_url = str(data.get("download_url") or "").strip()
        except Exception:
            pass

    actual_min = (min_supported or existing_min or VERSION).strip() or VERSION
    installer = f"{APP_NAME}-v{VERSION}-installer.exe"
    # download_url 支持指向外部对象存储（如腾讯云 COS 直链）；未显式传入时沿用已有配置，
    # 避免每次重新生成 version.json 把已配置的 CDN/COS 直链冲掉。
    actual_download_url = (
        download_url.strip() if download_url else existing_download_url
    ).strip()
    payload = {
        "latest": VERSION,
        "min_supported": actual_min,
        "installer": installer,
        "changelog": changelog.strip() or "1. 自动化剪辑新增失败项自动断点重试\n2. 优化版本兼容与配置体验",
    }
    if actual_download_url:
        payload["download_url"] = actual_download_url
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
    parser.add_argument(
        "--download-url",
        default=None,
        help="安装包下载直链（如腾讯云 COS / CDN 地址）；不传则沿用 version.json 中已有值",
    )
    args = parser.parse_args()
    path = write_release_version(
        changelog=args.changelog,
        min_supported=args.min_supported,
        download_url=args.download_url,
    )
    print(f"已写入 {path}")
    print(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
