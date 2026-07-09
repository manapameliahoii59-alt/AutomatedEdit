import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from scenedetect import ContentDetector, detect

from app.common.export_paths import build_clip_export_filename, resolve_project_export_dir
from app.common.ffmpeg_paths import resolve_ffmpeg, resolve_ffprobe
from app.common.outro_paths import outro_filename, resolve_outro_path
from app.data.models.drama_project import DramaProject

FONT_FILENAME = "msyh.ttc"
MIN_CUT_POINT = 0.1
MIN_CUT_DURATION = 0.3
CACHE_DIR_NAME = ".render_cache"


class RenderCancelled(RuntimeError):
    """用户取消渲染。"""


@dataclass(frozen=True)
class RenderResult:
    output_dir: str
    success_count: int
    total: int


@dataclass(frozen=True)
class ClipSegment:
    """单段素材：原片时间轴上的起止（秒）；end 为 None 表示到该集末尾。"""

    episode: str
    start: float
    end: float | None


@dataclass
class RenderContext:
    """一部剧渲染共享的预处理上下文。"""

    project_path: str
    target_w: int
    target_h: int
    use_gpu: bool
    enc_v: str
    episode_cache: dict[tuple[str, float], str] = field(default_factory=dict)
    probe_cache: dict[str, float | bool] = field(default_factory=dict)
    scene_cache: dict[str, list] = field(default_factory=dict)


class RenderService:

    @staticmethod
    def render(
        project: DramaProject,
        *,
        should_cancel: Callable[[], bool] | None = None,
        register_proc: Callable | None = None,
    ) -> RenderResult:
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

        if should_cancel and should_cancel():
            raise RenderCancelled("渲染已取消")

        output_dir = resolve_project_export_dir(project.name)

        RenderService._prepare_font()

        ffmpeg_kwargs = {
            "should_cancel": should_cancel,
            "register_proc": register_proc,
        }

        ctx = RenderService._build_render_context(
            ffmpeg, ffprobe, project_path, plans, **ffmpeg_kwargs
        )
        if ctx is None:
            raise FileNotFoundError(f"《{project.name}》未找到可用于判断画幅的视频文件")

        episodes, speeds = RenderService._collect_episodes_and_speeds(plans)
        if len(speeds) > 1:
            print(
                f"   ⚠️ 策划方案含多种倍速 {sorted(speeds)}，将分别缓存",
                flush=True,
            )

        print(
            f"   📦 预处理 {len(episodes)} 集缓存（倍速 {', '.join(str(s) for s in sorted(speeds))}）…",
            flush=True,
        )
        for speed in sorted(speeds):
            for ep_name in episodes:
                if should_cancel and should_cancel():
                    raise RenderCancelled("渲染已取消")
                cached = RenderService._ensure_episode_cached(
                    ffmpeg,
                    ffprobe,
                    ctx,
                    ep_name,
                    speed,
                    **ffmpeg_kwargs,
                )
                if not cached:
                    if should_cancel and should_cancel():
                        raise RenderCancelled("渲染已取消")
                    raise RuntimeError(f"集数缓存失败: {ep_name}")

        total = len(plans)
        success_count = 0
        print(
            f"\n🎬 开始渲染 《{project.name}》：共 {total} 条 -> {output_dir}",
            flush=True,
        )

        for i, plan in enumerate(plans):
            if should_cancel and should_cancel():
                raise RenderCancelled("渲染已取消")
            output_title = build_clip_export_filename(project.name, i + 1)
            print(f"   [进度 {i+1}/{total}] 渲染: {output_title}", flush=True)
            ok = RenderService._render_single(
                ffmpeg,
                ffprobe,
                output_dir,
                plan,
                project.name,
                output_title,
                ctx,
                **ffmpeg_kwargs,
            )
            if not ok:
                if should_cancel and should_cancel():
                    raise RenderCancelled("渲染已取消")
                continue
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
    def _natural_sort_key(name: str):
        return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", name)]

    @staticmethod
    def _collect_episodes_and_speeds(plans: list) -> tuple[list[str], set[float]]:
        episodes: set[str] = set()
        speeds: set[float] = set()
        for plan in plans:
            speeds.add(float(plan.get("global_speed", 1.0)))
            cfg = plan.get("files_config") or {}
            for ep in cfg.get("full_episodes") or []:
                episodes.add(ep)
            episodes.add(cfg["last_episode"])
        return sorted(episodes, key=RenderService._natural_sort_key), speeds

    @staticmethod
    def _build_render_context(
        ffmpeg,
        ffprobe,
        project_path: str,
        plans: list,
        *,
        should_cancel: Callable[[], bool] | None = None,
        register_proc: Callable | None = None,
    ) -> RenderContext | None:
        sample_path = RenderService._sample_video_path(project_path, plans[0])
        if not sample_path:
            return None
        orientation = RenderService._get_orientation(ffprobe, sample_path)
        is_horizontal = orientation == "horizontal"
        target_w, target_h = (1280, 720) if is_horizontal else (720, 1280)
        use_gpu = RenderService._has_nvenc(ffmpeg)
        enc_v = "h264_nvenc" if use_gpu else "libx264"
        return RenderContext(
            project_path=project_path,
            target_w=target_w,
            target_h=target_h,
            use_gpu=use_gpu,
            enc_v=enc_v,
        )

    @staticmethod
    def _sample_video_path(project_path: str, plan: dict) -> str | None:
        cfg = plan.get("files_config") or {}
        full_eps = cfg.get("full_episodes") or []
        sample_file = full_eps[0] if full_eps else cfg.get("last_episode")
        if not sample_file:
            return None
        path = os.path.join(project_path, sample_file)
        return path if os.path.isfile(path) else None

    @staticmethod
    def _cache_dir(project_path: str) -> str:
        path = os.path.join(project_path, CACHE_DIR_NAME)
        os.makedirs(path, exist_ok=True)
        return path

    @staticmethod
    def _cache_file_path(
        project_path: str,
        episode: str,
        speed: float,
        target_w: int,
        target_h: int,
        mtime: int,
    ) -> str:
        stem = os.path.splitext(os.path.basename(episode))[0]
        speed_tag = str(speed).replace(".", "p")
        name = f"{stem}_spd{speed_tag}_{target_w}x{target_h}_m{mtime}.mp4"
        return os.path.join(RenderService._cache_dir(project_path), name)

    @staticmethod
    def _map_time_to_cache(time_sec: float, speed: float) -> float:
        if speed <= 0:
            return time_sec
        return time_sec / speed

    @staticmethod
    def build_segments(config: dict, cut_point: float) -> list[ClipSegment]:
        """根据策划配置构建片段列表（原片时间轴）。"""
        full_episodes = config.get("full_episodes") or []
        first_cut_start = float(config.get("first_episode_cut_start", 0) or 0)
        last_episode = config["last_episode"]

        if not full_episodes:
            if cut_point <= first_cut_start:
                return []
            return [ClipSegment(last_episode, first_cut_start, cut_point)]

        segments: list[ClipSegment] = []
        for i, ep in enumerate(full_episodes):
            start = first_cut_start if i == 0 else 0.0
            segments.append(ClipSegment(ep, start, None))
        segments.append(ClipSegment(last_episode, 0.0, cut_point))
        return segments

    @staticmethod
    def _estimate_segment_duration(
        ffprobe,
        ctx: RenderContext,
        segment: ClipSegment,
        speed: float,
    ) -> float:
        cache_key = (segment.episode, speed)
        cached_path = ctx.episode_cache.get(cache_key)
        if not cached_path:
            return 0.0
        total = RenderService._probe_duration(ffprobe, cached_path, ctx.probe_cache)
        start_c = RenderService._map_time_to_cache(segment.start, speed)
        if segment.end is None:
            return max(0.0, total - start_c)
        end_c = RenderService._map_time_to_cache(segment.end, speed)
        return max(0.0, end_c - start_c)

    @staticmethod
    def _ensure_episode_cached(
        ffmpeg,
        ffprobe,
        ctx: RenderContext,
        episode: str,
        speed: float,
        *,
        should_cancel: Callable[[], bool] | None = None,
        register_proc: Callable | None = None,
    ) -> str | None:
        cache_key = (episode, speed)
        if cache_key in ctx.episode_cache:
            return ctx.episode_cache[cache_key]

        src_path = os.path.join(ctx.project_path, episode)
        if not os.path.isfile(src_path):
            print(f"⚠️ 找不到源视频: {src_path}", flush=True)
            return None

        mtime = int(os.path.getmtime(src_path))
        cache_path = RenderService._cache_file_path(
            ctx.project_path, episode, speed, ctx.target_w, ctx.target_h, mtime
        )
        if (
            os.path.isfile(cache_path)
            and RenderService._probe_duration(ffprobe, cache_path, ctx.probe_cache) > MIN_CUT_DURATION
            and RenderService._has_video_stream(ffprobe, cache_path, ctx.probe_cache)
        ):
            ctx.episode_cache[cache_key] = cache_path
            return cache_path

        w, h = ctx.target_w, ctx.target_h
        vf = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1,setpts=1/{speed}*PTS"
        )
        af = f"aresample=44100,aformat=channel_layouts=stereo,atempo={speed}"

        has_audio = RenderService._has_audio_stream(ffprobe, src_path, ctx.probe_cache)
        cmd = [ffmpeg, "-y", "-i", src_path]
        if has_audio:
            cmd.extend(["-vf", vf, "-af", af, "-map", "0:v:0", "-map", "0:a:0"])
        else:
            cmd.extend(
                [
                    "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                    "-vf", vf,
                    "-filter:a", af,
                    "-map", "0:v:0", "-map", "1:a:0",
                    "-shortest",
                ]
            )
        cmd.extend(["-c:v", ctx.enc_v, "-preset", "p4" if ctx.use_gpu else "veryfast"])
        if ctx.use_gpu:
            cmd.extend(["-cq", "24"])
        else:
            cmd.extend(["-crf", "22"])
        cmd.extend(["-c:a", "aac", "-b:a", "128k", cache_path])

        label = f"缓存 {episode}×{speed}"
        if not RenderService._run_ffmpeg(
            cmd, label, should_cancel=should_cancel, register_proc=register_proc
        ):
            return None
        if not RenderService._validate_output(ffprobe, cache_path, ctx.probe_cache):
            print(f"⚠️ 缓存产物无效: {cache_path}", flush=True)
            if os.path.exists(cache_path):
                os.remove(cache_path)
            return None

        ctx.episode_cache[cache_key] = cache_path
        return cache_path

    @staticmethod
    def _get_orientation(ffprobe, video_path, probe_cache: dict | None = None):
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
    def _get_scene_list(video_path: str, scene_cache: dict[str, list]) -> list:
        if video_path not in scene_cache:
            scene_cache[video_path] = detect(video_path, ContentDetector(threshold=27.0))
        return scene_cache[video_path]

    @staticmethod
    def _optimize_cut(video_path, ai_cut_time, scene_cache: dict[str, list], tolerance=1.5):
        try:
            scene_list = RenderService._get_scene_list(video_path, scene_cache)
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
    def _resolve_cut_point(
        ffprobe,
        video_path: str,
        ai_cut_time: float,
        scene_cache: dict[str, list],
    ) -> float:
        ai_cut_time = float(ai_cut_time)
        optimized = RenderService._optimize_cut(video_path, ai_cut_time, scene_cache)
        if optimized < MIN_CUT_POINT:
            return ai_cut_time
        return optimized

    @staticmethod
    def _has_video_stream(ffprobe, path, probe_cache: dict | None = None) -> bool:
        cache_key = f"has_v:{path}"
        if probe_cache is not None and cache_key in probe_cache:
            return bool(probe_cache[cache_key])
        try:
            proc = subprocess.run(
                [
                    ffprobe, "-v", "error",
                    "-select_streams", "v",
                    "-show_entries", "stream=index",
                    "-of", "csv=p=0",
                    path,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            result = bool(proc.stdout.strip())
        except Exception:
            result = False
        if probe_cache is not None:
            probe_cache[cache_key] = result
        return result

    @staticmethod
    def _probe_duration(ffprobe, path, probe_cache: dict | None = None) -> float:
        cache_key = f"dur:{path}"
        if probe_cache is not None and cache_key in probe_cache:
            return float(probe_cache[cache_key])
        try:
            proc = subprocess.run(
                [
                    ffprobe, "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "csv=p=0",
                    path,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            result = float(proc.stdout.strip() or 0)
        except Exception:
            result = 0.0
        if probe_cache is not None:
            probe_cache[cache_key] = result
        return result

    @staticmethod
    def _validate_output(ffprobe, path, probe_cache: dict | None = None) -> bool:
        if not RenderService._has_video_stream(ffprobe, path, probe_cache):
            return False
        return RenderService._probe_duration(ffprobe, path, probe_cache) >= MIN_CUT_DURATION

    @staticmethod
    def _quiet_ffmpeg_cmd(cmd: list) -> list:
        if not cmd:
            return cmd
        return [cmd[0], "-hide_banner", "-nostats", "-loglevel", "error", *cmd[1:]]

    @staticmethod
    def _run_ffmpeg(
        cmd,
        desc,
        *,
        should_cancel: Callable[[], bool] | None = None,
        register_proc: Callable | None = None,
    ):
        proc = None
        cmd = RenderService._quiet_ffmpeg_cmd(cmd)
        try:
            print(f"   ▶ {desc}…", flush=True)
            with tempfile.TemporaryFile(mode="w+b") as stderr_sink:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=stderr_sink,
                )
                if register_proc:
                    register_proc(proc)
                while proc.poll() is None:
                    if should_cancel and should_cancel():
                        proc.kill()
                        proc.wait()
                        print(f"⏹ {desc} 已取消", flush=True)
                        return False
                    time.sleep(0.25)
                stderr_sink.seek(0)
                stderr = stderr_sink.read().decode("utf-8", errors="ignore").strip()
                if proc.returncode != 0:
                    if stderr:
                        print(f"❌ {desc} 失败: {stderr}", flush=True)
                    else:
                        print(f"❌ {desc} 失败，退出码: {proc.returncode}", flush=True)
                return proc.returncode == 0
        except Exception as e:
            print(f"❌ {desc} 异常: {e}", flush=True)
            return False
        finally:
            if register_proc:
                register_proc(None)

    @staticmethod
    def _has_audio_stream(ffprobe, path, probe_cache: dict | None = None) -> bool:
        cache_key = f"has_a:{path}"
        if probe_cache is not None and cache_key in probe_cache:
            return bool(probe_cache[cache_key])
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
            result = bool(proc.stdout.strip())
        except Exception:
            result = False
        if probe_cache is not None:
            probe_cache[cache_key] = result
        return result

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
    def _build_trim_filters(segment: ClipSegment, speed: float) -> tuple[str, str]:
        start_c = RenderService._map_time_to_cache(segment.start, speed)
        if segment.end is None:
            v_trim = f"trim=start={start_c:.3f},setpts=PTS-STARTPTS"
            a_trim = f"atrim=start={start_c:.3f},asetpts=PTS-STARTPTS"
        else:
            end_c = RenderService._map_time_to_cache(segment.end, speed)
            v_trim = f"trim=start={start_c:.3f}:end={end_c:.3f},setpts=PTS-STARTPTS"
            a_trim = f"atrim=start={start_c:.3f}:end={end_c:.3f},asetpts=PTS-STARTPTS"
        return v_trim, a_trim

    @staticmethod
    def _render_single(
        ffmpeg,
        ffprobe,
        output_dir,
        plan,
        project_name,
        output_title,
        ctx: RenderContext,
        *,
        should_cancel: Callable[[], bool] | None = None,
        register_proc: Callable | None = None,
    ):
        if should_cancel and should_cancel():
            return False
        ffmpeg_kwargs = {
            "should_cancel": should_cancel,
            "register_proc": register_proc,
        }
        config = plan["files_config"]
        speed = float(plan.get("global_speed", 1.0))
        output_path = os.path.join(output_dir, f"{output_title}.mp4")

        is_horizontal = ctx.target_w >= ctx.target_h
        outro_path = resolve_outro_path(is_horizontal)
        if not outro_path:
            name = outro_filename(is_horizontal)
            print(f"⚠️ 找不到片尾素材 {name}，请将文件放入 tools/outro/ 目录")
            return False

        last_file = os.path.join(ctx.project_path, config["last_episode"])
        ai_cut_point = config["last_episode_cut_point"]
        print(f"   分析切点: {output_title}", flush=True)
        cut_point = RenderService._resolve_cut_point(
            ffprobe, last_file, ai_cut_point, ctx.scene_cache
        )
        if cut_point <= 0:
            print(
                f"⚠️ 无效切点: last_episode_cut_point({ai_cut_point}) "
                f"优化后为 {cut_point}，跳过"
            )
            return False
        if cut_point != ai_cut_point:
            print(f"   切点优化: {ai_cut_point}s -> {cut_point}s")

        segments = RenderService.build_segments(config, cut_point)
        if not segments:
            print("⚠️ 无效片段配置，跳过", flush=True)
            return False

        input_paths: list[str] = []
        for segment in segments:
            cache_key = (segment.episode, speed)
            cached = ctx.episode_cache.get(cache_key)
            if not cached or not os.path.isfile(cached):
                print(f"⚠️ 缺少缓存: {segment.episode}，跳过", flush=True)
                return False
            input_paths.append(cached)

        estimated = sum(
            RenderService._estimate_segment_duration(ffprobe, ctx, seg, speed)
            for seg in segments
        )
        if estimated < MIN_CUT_DURATION:
            print(
                f"⚠️ 预估成片时长过短（{estimated:.2f}s < {MIN_CUT_DURATION}s），跳过",
                flush=True,
            )
            return False

        title_f = (
            f"drawtext=fontfile={FONT_FILENAME}:text='《{project_name}》':"
            f"x=30:y=h-70:fontsize=22:fontcolor=white@0.8"
        )
        disclaim_f = (
            f"drawtext=fontfile={FONT_FILENAME}:text='内容纯属虚构 请勿带入现实':"
            f"x=30:y=h-40:fontsize=14:fontcolor=white@0.6"
        )
        v_outro = (
            f"scale={ctx.target_w}:{ctx.target_h}:force_original_aspect_ratio=decrease,"
            f"pad={ctx.target_w}:{ctx.target_h}:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1"
        )
        a_outro = "aresample=44100,aformat=channel_layouts=stereo"

        filter_parts: list[str] = []
        n_main = len(segments)
        for i, segment in enumerate(segments):
            v_trim, a_trim = RenderService._build_trim_filters(segment, speed)
            filter_parts.append(
                f"[{i}:v]{v_trim},{title_f},{disclaim_f}[v{i}];[{i}:a]{a_trim}[a{i}];"
            )
        outro_idx = n_main
        filter_parts.append(f"[{outro_idx}:v]{v_outro}[v{outro_idx}];")
        filter_parts.append(f"[{outro_idx}:a]{a_outro}[a{outro_idx}];")
        concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(n_main))
        concat_inputs += f"[v{outro_idx}][a{outro_idx}]"
        filter_parts.append(f"{concat_inputs}concat=n={n_main + 1}:v=1:a=1[v][a]")

        render_cmd = [ffmpeg, "-y"]
        for p in input_paths:
            render_cmd.extend(["-i", p])
        render_cmd.extend(["-i", outro_path])
        render_cmd.extend(["-filter_complex", "".join(filter_parts), "-map", "[v]", "-map", "[a]"])
        render_cmd.extend(["-c:v", ctx.enc_v, "-preset", "p4" if ctx.use_gpu else "veryfast"])
        if ctx.use_gpu:
            render_cmd.extend(["-cq", "24"])
        else:
            render_cmd.extend(["-crf", "22"])
        render_cmd.extend(["-c:a", "aac", "-b:a", "192k", output_path])

        success = RenderService._run_ffmpeg(render_cmd, "合成渲染", **ffmpeg_kwargs)
        if success and not RenderService._validate_output(ffprobe, output_path, ctx.probe_cache):
            print(f"⚠️ 成片无效（时长需 >= {MIN_CUT_DURATION}s），跳过", flush=True)
            if os.path.exists(output_path):
                os.remove(output_path)
            return False
        return success
