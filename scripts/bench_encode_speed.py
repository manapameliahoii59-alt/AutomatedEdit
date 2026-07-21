"""CLI: 对比一部剧 CPU / GPU 完整渲染速度（集数缓存 + 成片合成）。

用法:
  python scripts/bench_encode_speed.py [剧名关键词]
  python scripts/bench_encode_speed.py --cpu [剧名关键词]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.common.ffmpeg_paths import ensure_bundled_ffmpeg_on_path
from app.data.models.drama_project import DramaProject
from app.data.services.render_service import RenderService


def _natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def main() -> int:
    ensure_bundled_ffmpeg_on_path()
    args = [a for a in sys.argv[1:] if a]
    cpu_only = False
    if "--cpu" in args:
        cpu_only = True
        args = [a for a in args if a != "--cpu"]

    root = Path.home() / "Desktop" / "视频下载"
    if not root.is_dir():
        print(f"未找到下载目录: {root}")
        return 1

    keyword = args[0] if args else "摆摊"
    chosen = None
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        has_plan = (p / "production_plan_v3.json").is_file() or (
            p / ".automatededit" / "production_plan_v3.json"
        ).is_file()
        if not has_plan:
            continue
        if keyword in p.name:
            chosen = p
            break
        chosen = chosen or p

    if chosen is None:
        print("没有找到已策划的剧目")
        return 1

    videos = sorted([f.name for f in chosen.glob("*.mp4")], key=_natural_key)
    project = DramaProject(
        id="bench",
        name=chosen.name,
        episode_count=len(videos),
        folder_path=str(chosen),
        video_files=tuple(str(chosen / v) for v in videos),
    )
    mode = "仅 CPU" if cpu_only else "CPU vs GPU"
    print(f"测试剧目: {project.name} ({len(videos)} 集) [{mode}]", flush=True)
    result = RenderService.benchmark_encode_speed(project, cpu_only=cpu_only)
    print(result.message, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
