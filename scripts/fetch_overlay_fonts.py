"""拉取叠字内置字体到 tools/fonts（目前自动下载开源思源中宋）。"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONTS_DIR = ROOT / "tools" / "fonts"

# (目标文件名, 镜像列表)
_DOWNLOADS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "NotoSerifSC-Medium.otf",
        (
            "https://cdn.jsdelivr.net/gh/notofonts/noto-cjk@main/Serif/SubsetOTF/SC/NotoSerifSC-Medium.otf",
            "https://github.com/notofonts/noto-cjk/raw/main/Serif/SubsetOTF/SC/NotoSerifSC-Medium.otf",
        ),
    ),
)


def _download(url: str, dest: Path) -> bool:
    try:
        print(f"  GET {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "AutomatedEdit-font-fetch"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = resp.read()
        if len(data) < 1_000_000:
            print(f"  skip (too small: {len(data)} bytes)")
            return False
        dest.write_bytes(data)
        print(f"  saved {dest.name} ({len(data)} bytes)")
        return True
    except Exception as exc:
        print(f"  failed: {exc}")
        return False


def main() -> int:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    ok = 0
    for filename, urls in _DOWNLOADS:
        dest = FONTS_DIR / filename
        if dest.is_file() and dest.stat().st_size > 1_000_000:
            print(f"exists: {filename}")
            ok += 1
            continue
        print(f"fetch: {filename}")
        for url in urls:
            if _download(url, dest):
                ok += 1
                break
        else:
            print(f"ERROR: could not download {filename}")
    print(f"done: {ok}/{len(_DOWNLOADS)}")
    print(f"place other fonts into: {FONTS_DIR}")
    return 0 if ok == len(_DOWNLOADS) else 1


if __name__ == "__main__":
    sys.exit(main())
