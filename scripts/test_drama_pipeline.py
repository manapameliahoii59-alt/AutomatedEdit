"""下载 → 识别 → 策划（远程 API）→ 渲染，用于冒烟测一部剧。

用法:
  uv run python scripts/test_drama_pipeline.py 女配逆袭
  uv run python scripts/test_drama_pipeline.py 女配逆袭 --from 1 --to 15
  uv run python scripts/test_drama_pipeline.py 女配逆袭 --skip-download --folder "C:/.../女配逆袭"
"""

from __future__ import annotations

# Windows：须先加载 torch，再碰 PySide6，否则 WinError 1114
import torch  # noqa: F401

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("AV_LOG_LEVEL", "quiet")
os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")


def _download_and_transcribe(name: str, from_ep: int, to_ep: int) -> Path:
    from app.data.services.batch_download_service import (
        BatchDownloadOptions,
        run_batch_download,
    )
    from app.data.services.changdu_paths import DEFAULT_DOWNLOAD_DIR

    print(f"\n========== 下载+识别: 《{name}》 {from_ep}-{to_ep} ==========", flush=True)
    summary = run_batch_download(
        [{"name": name, "from": from_ep, "to": to_ep}],
        BatchDownloadOptions(
            from_ep=from_ep,
            to_ep=to_ep,
            skip_done=False,
            auto_transcribe=True,
            auto_unzip_and_delete=True,
        ),
    )
    print(f"下载汇总: {json.dumps(summary, ensure_ascii=False, default=str)}", flush=True)
    folders = summary.get("transcribed_folders") or []
    if folders:
        return Path(folders[0])

    root = Path(DEFAULT_DOWNLOAD_DIR)
    for p in sorted(root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_dir() and name in p.name:
            return p
    raise FileNotFoundError(f"未找到《{name}》解压目录（download_dir={root}）")


def _resolve_folder(name: str, folder_arg: str) -> Path:
    if folder_arg:
        p = Path(folder_arg)
        if not p.is_dir():
            raise FileNotFoundError(p)
        return p
    from app.data.services.changdu_paths import DEFAULT_DOWNLOAD_DIR

    root = Path(DEFAULT_DOWNLOAD_DIR)
    cands = [p for p in root.iterdir() if p.is_dir() and name in p.name]
    if not cands:
        raise FileNotFoundError(f"未找到含「{name}」的目录于 {root}")
    cands.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return cands[0]


def _transcribe_only(folder: Path, project_name: str) -> None:
    from app.common.drama_artifact_paths import locate_script_data
    from app.data.models.drama_project import DramaProject
    from app.data.services.transcription_service import TranscriptionService

    if locate_script_data(str(folder)):
        print(f"已有识别产物，跳过识别: {folder}", flush=True)
        return
    mp4_count = len([f for f in os.listdir(folder) if f.lower().endswith(".mp4")])
    print(f"\n========== 识别 《{project_name}》（{mp4_count} 集） ==========", flush=True)
    project = DramaProject(
        id="test-pipeline",
        name=project_name,
        episode_count=mp4_count,
        folder_path=str(folder),
    )
    TranscriptionService.transcribe(project)
    print("识别完成", flush=True)


def _remote_plan(folder: Path, project_name: str) -> dict:
    from app.common.plan_settings import resolve_active_plan_params
    from app.data.api.api import get_api
    from app.data.models.drama_project import DramaProject
    from app.data.services.ai_director_service import AIDirectorService

    api = get_api()
    state = api.check_session()
    if state != "valid":
        raise RuntimeError(
            f"登录态无效（{state}），请先在客户端登录后再跑本脚本"
        )

    params = resolve_active_plan_params()
    mp4_count = len([f for f in os.listdir(folder) if f.lower().endswith(".mp4")])
    print(
        f"\n========== 远程策划 《{project_name}》 ==========\n"
        f"mode={params['mode']} count={params['clip_count']} "
        f"dur={params['min_duration_sec']}-{params['max_duration_sec']}s "
        f"split_ab={params['split_ab']}\n"
        f"视频集数={mp4_count}",
        flush=True,
    )

    project = DramaProject(
        id="test-pipeline",
        name=project_name,
        episode_count=mp4_count,
        folder_path=str(folder),
    )

    def on_progress(p: dict) -> None:
        print(
            f"  进度 {p.get('current')}/{p.get('total')} {p.get('detail') or ''}",
            flush=True,
        )

    result = AIDirectorService.plan(project, progress_callback=on_progress)
    print(f"策划结果: {json.dumps(result, ensure_ascii=False)}", flush=True)
    return result


def _render(folder: Path, project_name: str) -> None:
    from app.data.models.drama_project import DramaProject
    from app.data.services.render_service import RenderService

    print(f"\n========== 渲染 《{project_name}》 ==========", flush=True)
    mp4_count = len([f for f in os.listdir(folder) if f.lower().endswith(".mp4")])
    project = DramaProject(
        id="test-pipeline",
        name=project_name,
        episode_count=mp4_count,
        folder_path=str(folder),
    )
    result = RenderService.render(project)
    print(
        f"渲染结果: success={result.success_count}/{result.total}",
        flush=True,
    )
    if result.success_count <= 0:
        raise RuntimeError("渲染未成功产出成片")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("name", nargs="?", default="女配逆袭")
    parser.add_argument("--from", dest="from_ep", type=int, default=1)
    parser.add_argument("--to", dest="to_ep", type=int, default=15)
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--folder", default="")
    parser.add_argument("--skip-render", action="store_true")
    parser.add_argument("--skip-plan", action="store_true")
    args = parser.parse_args()

    name = args.name.strip()
    if args.skip_download:
        folder = _resolve_folder(name, args.folder)
    else:
        folder = _download_and_transcribe(name, args.from_ep, args.to_ep)

    print(f"剧目目录: {folder}", flush=True)
    mp4s = sorted(p.name for p in folder.glob("*.mp4"))
    print(
        f"视频文件数: {len(mp4s)} → {mp4s[:8]}{'…' if len(mp4s) > 8 else ''}",
        flush=True,
    )

    # 下载阶段识别可能因 DLL 顺序失败；此处再补一次
    _transcribe_only(folder, name)

    if not args.skip_plan:
        _remote_plan(folder, name)
    if not args.skip_render:
        _render(folder, name)

    print("\n✅ 全流程完成", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
