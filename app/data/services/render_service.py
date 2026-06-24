import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass

from scenedetect import detect, ContentDetector

from app.common.export_paths import resolve_project_export_dir
from app.common.ffmpeg_paths import resolve_ffmpeg, resolve_ffprobe
from app.common.outro_paths import outro_filename, resolve_outro_path
from app.data.models.drama_project import DramaProject

FONT_FILENAME = "msyh.ttc"


@dataclass(frozen=True)
class RenderResult:
    output_dir: str
    success_count: int
    total: int


class RenderService:

    @staticmethod
    def render(project: DramaProject) -> RenderResult:
        ffmpeg = resolve_ffmpeg()
        ffprobe = resolve_ffprobe()

        project_path = project.folder_path
        plan_path = os.path.join(project_path, "production_plan_v3.json")
        if not os.path.exists(plan_path):
            raise FileNotFoundError(f"《{project.name}》未找到 production_plan_v3.json，请先 AI 策划")

        from app.common.crypto import read_json
        plans = read_json(plan_path)

        if not plans:
            raise RuntimeError(f"《{project.name}》策划方案为空")

        output_dir = resolve_project_export_dir(project.name)

        RenderService._prepare_font()

        total = len(plans)
        success_count = 0

        for i, plan in enumerate(plans):
            print(f"   [进度 {i+1}/{total}] 渲染: {plan.get('title', '')}")
            ok = RenderService._render_single(
                ffmpeg, ffprobe, project_path, output_dir, plan, project.name
            )
            if ok:
                success_count += 1

        print(f"✅ 《{project.name}》渲染完成: {success_count}/{total} 条")
        return RenderResult(output_dir, success_count, total)

    @staticmethod
    def _prepare_font():
        system_font = os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", FONT_FILENAME)
        if not os.path.exists(FONT_FILENAME) and os.path.exists(system_font):
            try:
                shutil.copy(system_font, FONT_FILENAME)
            except Exception:
                pass

    @staticmethod
    def _get_orientation(ffprobe, video_path):
        try:
            cmd = [
                ffprobe, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=s=x:p=0",
                video_path,
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
            out = proc.stdout.strip()
            if "x" in out:
                w, h = map(int, out.split("x"))
                return "horizontal" if w >= h else "vertical"
        except Exception:
            pass
        return "vertical"

    @staticmethod
    def _optimize_cut(ffprobe, video_path, ai_cut_time, tolerance=1.5):
        try:
            scene_list = detect(video_path, ContentDetector(threshold=27.0))
            nearest = ai_cut_time
            for scene in scene_list:
                cut = scene[0].get_seconds()
                diff = abs(cut - ai_cut_time)
                if diff <= tolerance:
                    nearest = cut
                    tolerance = diff
            return nearest
        except Exception:
            return ai_cut_time

    @staticmethod
    def _run_ffmpeg(cmd, desc):
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=3600)
            if proc.returncode != 0:
                print(f"❌ {desc} 失败: {proc.stderr}")
            return proc.returncode == 0
        except Exception as e:
            print(f"❌ {desc} 异常: {e}")
            return False

    @staticmethod
    def _has_audio_stream(ffprobe, path) -> bool:
        try:
            proc = subprocess.run(
                [
                    ffprobe, "-v", "error",
                    "-select_streams", "a",
                    "-show_entries", "stream=index",
                    "-of", "csv=p=0",
                    path,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return bool(proc.stdout.strip())
        except Exception:
            return False

    @staticmethod
    def _ensure_audio_track(ffmpeg, ffprobe, path, tag) -> tuple[str, str | None]:
        if RenderService._has_audio_stream(ffprobe, path):
            return path, None
        fixed = f"temp_audiofix_{tag}.mp4"
        cmd = [
            ffmpeg, "-y", "-i", path,
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            fixed,
        ]
        if RenderService._run_ffmpeg(cmd, "补音轨"):
            return fixed, fixed
        return path, None

    @staticmethod
    def _cut_cmd(ffmpeg, inputs: list, output: str, enc_v: str) -> list:
        cmd = [ffmpeg, "-y", *inputs, "-map", "0:v:0", "-map", "0:a:0?"]
        cmd.extend(["-c:v", enc_v, "-c:a", "aac", "-b:a", "128k", output])
        return cmd

    @staticmethod
    def _has_nvenc(ffmpeg: str) -> bool:
        try:
            proc = subprocess.run(
                [ffmpeg, "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return "h264_nvenc" in proc.stdout
        except Exception:
            return False

    @staticmethod
    def _render_single(ffmpeg, ffprobe, project_path, output_dir, plan, project_name):
        config = plan["files_config"]
        speed = plan.get("global_speed", 1.0)
        title = plan.get("title", f"task-{uuid.uuid4().hex[:4]}")
        output_path = os.path.join(output_dir, f"{title}.mp4")
        uid = uuid.uuid4().hex[:8]

        last_file = os.path.join(project_path, config["last_episode"])
        full_eps = config.get("full_episodes") or []
        sample_file = full_eps[0] if full_eps else config["last_episode"]
        sample_path = os.path.join(project_path, sample_file)

        orientation = RenderService._get_orientation(ffprobe, sample_path)
        is_horizontal = orientation == "horizontal"
        if is_horizontal:
            target_w, target_h = 1280, 720
        else:
            target_w, target_h = 720, 1280

        outro_path = resolve_outro_path(is_horizontal)
        if not outro_path:
            name = outro_filename(is_horizontal)
            print(f"⚠️ 找不到片尾素材 {name}，请将文件放入 tools/outro/ 目录")
            return False

        temp_cut = f"temp_last_{uid}.mp4"
        cut_point = RenderService._optimize_cut(ffprobe, last_file, config["last_episode_cut_point"])
        use_gpu = RenderService._has_nvenc(ffmpeg)
        enc_v_cut = "libx264"
        enc_v_final = "h264_nvenc" if use_gpu else "libx264"
        first_cut_start = config.get("first_episode_cut_start", 0)
        full_episodes = config.get("full_episodes") or []

        input_paths = []
        temp_first = None
        temp_audiofix: list[str] = []

        if not full_episodes:
            span = cut_point - first_cut_start
            if span <= 0:
                print(f"⚠️ 无效切点: last_episode_cut_point({cut_point}) <= first_episode_cut_start({first_cut_start})")
                return False
            cut_cmd = RenderService._cut_cmd(
                ffmpeg,
                ["-ss", str(first_cut_start), "-i", last_file, "-t", str(span)],
                temp_cut,
                enc_v_cut,
            )
            if not RenderService._run_ffmpeg(cut_cmd, "预切割"):
                return False
            input_paths.append(temp_cut)
        else:
            cut_cmd = RenderService._cut_cmd(
                ffmpeg,
                ["-i", last_file, "-t", str(cut_point)],
                temp_cut,
                enc_v_cut,
            )
            if not RenderService._run_ffmpeg(cut_cmd, "预切割"):
                return False

        for i, full_file in enumerate(full_episodes):
            full_path = os.path.join(project_path, full_file)
            if i == 0 and first_cut_start > 0:
                temp_first = f"temp_first_{uid}.mp4"
                cut_first_cmd = RenderService._cut_cmd(
                    ffmpeg,
                    ["-ss", str(first_cut_start), "-i", full_path],
                    temp_first,
                    enc_v_cut,
                )
                if RenderService._run_ffmpeg(cut_first_cmd, "裁剪开场"):
                    input_paths.append(temp_first)
                else:
                    input_paths.append(full_path)
            else:
                input_paths.append(full_path)
        if full_episodes:
            input_paths.append(temp_cut)

        normalized_paths = []
        for i, p in enumerate(input_paths):
            fixed, temp = RenderService._ensure_audio_track(ffmpeg, ffprobe, p, f"{uid}_{i}")
            normalized_paths.append(fixed)
            if temp:
                temp_audiofix.append(temp)
        input_paths = normalized_paths

        title_f = (
            f"drawtext=fontfile={FONT_FILENAME}:text='《{project_name}》':"
            f"x=30:y=h-70:fontsize=22:fontcolor=white@0.8"
        )
        disclaim_f = (
            f"drawtext=fontfile={FONT_FILENAME}:text='内容纯属虚构 请勿带入现实':"
            f"x=30:y=h-40:fontsize=14:fontcolor=white@0.6"
        )
        v_main = (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black,"
            f"setpts=1/{speed}*PTS,{title_f},{disclaim_f}"
        )
        a_main = f"aresample=44100,aformat=channel_layouts=stereo,atempo={speed}"
        v_outro = (
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
            f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:black"
        )
        a_outro = "aresample=44100,aformat=channel_layouts=stereo"

        filter_parts = []
        n_main = len(input_paths)
        for i in range(n_main):
            filter_parts.append(f"[{i}:v]{v_main}[v{i}];[{i}:a]{a_main}[a{i}];")
        outro_idx = n_main
        filter_parts.append(f"[{outro_idx}:v]{v_outro}[v{outro_idx}];")
        filter_parts.append(f"[{outro_idx}:a]{a_outro}[a{outro_idx}];")
        concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(n_main))
        concat_inputs += f"[v{outro_idx}][a{outro_idx}]"
        filter_parts.append(f"{concat_inputs}concat=n={n_main+1}:v=1:a=1[v][a]")

        render_cmd = [ffmpeg, "-y"]
        for p in input_paths:
            render_cmd.extend(["-i", p])
        render_cmd.extend(["-i", outro_path])
        render_cmd.extend(["-filter_complex", "".join(filter_parts), "-map", "[v]", "-map", "[a]"])
        render_cmd.extend(["-c:v", enc_v_final, "-preset", "p4" if use_gpu else "veryfast"])
        if use_gpu:
            render_cmd.extend(["-cq", "24"])
        else:
            render_cmd.extend(["-crf", "22"])
        render_cmd.extend(["-c:a", "aac", "-b:a", "192k", output_path])

        success = RenderService._run_ffmpeg(render_cmd, "最终渲染")

        if os.path.exists(temp_cut):
            os.remove(temp_cut)
        if temp_first and os.path.exists(temp_first):
            os.remove(temp_first)
        for p in temp_audiofix:
            if os.path.exists(p):
                os.remove(p)

        return success
