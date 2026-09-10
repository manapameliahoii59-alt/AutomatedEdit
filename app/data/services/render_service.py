import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace

from scenedetect import ContentDetector, detect

from app.common.export_paths import build_clip_export_filename, resolve_project_export_dir
from app.common.ffmpeg_paths import resolve_ffmpeg, resolve_ffprobe
from app.common.outro_paths import outro_filename, resolve_outro_path
from app.common.win_subprocess import popen as win_popen
from app.common.win_subprocess import run as win_run
from app.data.models.drama_project import DramaProject

FONT_FILENAME = "msyh.ttc"
MIN_CUT_POINT = 0.1
MIN_CUT_DURATION = 0.3
CACHE_DIR_NAME = ".render_cache"
# 切点优化只扫 AI 切点前后若干秒，避免整集 ContentDetector
SCENE_SCAN_RADIUS = 3.0
# 切点吸附下限：AI 切点 = 台词结束 + 尾垫（服务端 POST_CUT_PAD_SECONDS），
# 吸附不得早于台词结束点，否则最后一句话会被剪到一半
CUT_SPEECH_PAD_SECONDS = 0.3

# 阶段C：drawtext 层数超过该阈值（辉光类）才预渲为 PNG；纯文字保持 drawtext 原样
OVERLAY_BAKE_MIN_LAYERS = 4

# NVENC: p1 最慢最好 → p7 最快；默认 p5
NVENC_PRESET_CHOICES: tuple[tuple[str, str], ...] = (
    ("p1", "p1（最慢/画质最好）"),
    ("p2", "p2"),
    ("p3", "p3"),
    ("p4", "p4（平衡）"),
    ("p5", "p5（默认/更快）"),
    ("p6", "p6（很快）"),
    ("p7", "p7（最快）"),
)
# libx264: ultrafast 最快 → medium 更慢更好；默认 superfast
X264_PRESET_CHOICES: tuple[tuple[str, str], ...] = (
    ("ultrafast", "ultrafast（最快）"),
    ("superfast", "superfast（默认）"),
    ("veryfast", "veryfast"),
    ("faster", "faster"),
    ("fast", "fast"),
    ("medium", "medium（更慢/更好）"),
)
_DEFAULT_NVENC_PRESET = "p5"
_DEFAULT_X264_PRESET = "superfast"
_NVENC_PRESET_SET = {k for k, _ in NVENC_PRESET_CHOICES}
_X264_PRESET_SET = {k for k, _ in X264_PRESET_CHOICES}

# h264_amf: speed 最快 → quality 更慢更好；默认 speed（保持历史行为）
AMF_PRESET_CHOICES: tuple[tuple[str, str], ...] = (
    ("speed", "speed（默认/最快）"),
    ("balanced", "balanced（平衡）"),
    ("quality", "quality（更慢/更好）"),
)
# h264_qsv: veryfast 最快 → medium 更慢更好；默认 veryfast（保持历史行为）
QSV_PRESET_CHOICES: tuple[tuple[str, str], ...] = (
    ("veryfast", "veryfast（默认/最快）"),
    ("faster", "faster"),
    ("fast", "fast"),
    ("medium", "medium（更慢/更好）"),
)
_DEFAULT_AMF_PRESET = "speed"
_DEFAULT_QSV_PRESET = "veryfast"
_AMF_PRESET_SET = {k for k, _ in AMF_PRESET_CHOICES}
_QSV_PRESET_SET = {k for k, _ in QSV_PRESET_CHOICES}

# 成片分辨率：720p / 1080p / source（跟随原片）
RESOLUTION_CHOICES: tuple[tuple[str, str], ...] = (
    ("720p", "720p（默认，体积小）"),
    ("1080p", "1080p（更清晰，体积约 2 倍）"),
    ("source", "跟随原片分辨率"),
)
_DEFAULT_RESOLUTION = "720p"
_RESOLUTION_SET = {k for k, _ in RESOLUTION_CHOICES}
# 固定档位尺寸（宽, 高），按画幅方向取用
_RESOLUTION_DIMS = {
    "720p": {"horizontal": (1280, 720), "vertical": (720, 1280)},
    "1080p": {"horizontal": (1920, 1080), "vertical": (1080, 1920)},
}


def build_atempo_filter(speed: float) -> str:
    """生成 atempo 链。单级通常限 0.5~2.0，超过则拆成多级（如 3x → 2.0,1.5）。"""
    try:
        rate = float(speed)
    except (TypeError, ValueError):
        rate = 1.0
    if rate != rate or rate <= 0:
        rate = 1.0
    factors: list[float] = []
    remaining = rate
    while remaining > 2.0 + 1e-9:
        factors.append(2.0)
        remaining /= 2.0
    while remaining < 0.5 - 1e-9:
        factors.append(0.5)
        remaining /= 0.5
    factors.append(round(remaining, 4))
    return ",".join(f"atempo={f:g}" for f in factors)


def _safe_print(*args, **kwargs) -> None:
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        cleaned = [
            a.encode("gbk", errors="ignore").decode("gbk") if isinstance(a, str) else a
            for a in args
        ]
        print(*cleaned, **kwargs)


@dataclass(frozen=True)
class HardwareEncoderInfo:
    codec_name: str  # "h264_nvenc" | "h264_amf" | "h264_qsv" | "libx264"
    vendor_label: str  # "NVIDIA NVENC" | "AMD AMF" | "Intel QSV" | "CPU(libx264)"
    is_gpu: bool


class RenderCancelled(RuntimeError):
    """用户取消渲染。"""


@dataclass(frozen=True)
class RenderResult:
    output_dir: str
    success_count: int
    total: int
    total_seconds: float = 0.0
    cache_seconds: float = 0.0
    compose_seconds: float = 0.0
    total_video_seconds: float = 0.0
    speed_ratio: float = 0.0


@dataclass(frozen=True)
class EncodeBenchmarkResult:
    """CPU / GPU 完整渲染对比：集数缓存 + 成片合成。"""

    project_name: str
    episode_count: int
    plan_count: int
    speeds: tuple[float, ...]
    cpu_cache_seconds: float
    cpu_compose_seconds: float
    cpu_total_seconds: float
    gpu_cache_seconds: float | None
    gpu_compose_seconds: float | None
    gpu_total_seconds: float | None
    gpu_available: bool
    message: str


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
    scene_cache: dict = field(default_factory=dict)
    continued_card_hits: dict[str, bool] = field(default_factory=dict)
    # 阶段B：跨方案共享的「公共前缀」缓存（key -> 已编码文件路径）
    prefix_cache: dict = field(default_factory=dict)
    # 使用次数 >= 2 的公共前缀 key 集合；非空时才启用前缀复用
    prefix_keys: set = field(default_factory=set)
    # 本次渲染的临时目录，用于存放公共前缀/尾部片段
    prefix_dir: str = ""


class RenderService:
    _cached_hardware_encoder: HardwareEncoderInfo | None = None

    @classmethod
    def clear_encoder_cache(cls) -> None:
        """清空显卡硬件探测缓存（供设置变更或测试隔离使用）。"""
        cls._cached_hardware_encoder = None

    @staticmethod
    def detect_active_encoder() -> HardwareEncoderInfo:
        """探测当前生效的编码器（供设置界面展示对应档位）。失败回退 CPU。"""
        try:
            from app.common.ffmpeg_paths import resolve_ffmpeg

            return RenderService._detect_best_encoder(resolve_ffmpeg())
        except Exception:
            return HardwareEncoderInfo("libx264", "CPU(libx264)", is_gpu=False)

    @staticmethod
    def benchmark_encode_speed(
        project: DramaProject,
        *,
        max_episodes: int | None = None,
        max_plans: int | None = None,
        cpu_only: bool = False,
        should_cancel: Callable[[], bool] | None = None,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> EncodeBenchmarkResult:
        """完整渲染测速：集数缓存 + 成片合成。

        默认对比 CPU / GPU；``cpu_only=True`` 时只跑 CPU(libx264)。
        会清空该剧 `.render_cache`，成片输出到导出目录下的 `_bench_cpu` / `_bench_gpu`。
        """
        ffmpeg = resolve_ffmpeg()
        ffprobe = resolve_ffprobe()
        from app.common.crypto import read_json
        from app.common.drama_artifact_paths import locate_production_plan

        plan_path = locate_production_plan(project.folder_path)
        if not plan_path:
            raise FileNotFoundError(
                f"《{project.name}》未找到策划文件，请先完成策划"
            )
        plans = read_json(plan_path)
        if not plans:
            raise RuntimeError(f"《{project.name}》策划方案为空")
        if max_plans is not None and max_plans > 0:
            plans = plans[:max_plans]

        RenderService._prepare_font()
        base_ctx = RenderService._build_render_context(
            ffmpeg, ffprobe, project.folder_path, plans
        )
        if base_ctx is None:
            raise FileNotFoundError(f"《{project.name}》未找到可用视频")

        episodes, speeds = RenderService._collect_episodes_and_speeds(plans)
        if max_episodes is not None and max_episodes > 0:
            episodes = episodes[:max_episodes]
        if not episodes:
            raise RuntimeError("没有可测试的集数")

        best_enc = RenderService._detect_best_encoder(ffmpeg, allow_gpu=True)
        gpu_ok = False if cpu_only else best_enc.is_gpu
        gpu_label = f"GPU({best_enc.vendor_label})"
        speeds_t = tuple(sorted(speeds))
        export_root = resolve_project_export_dir(project.name)

        def _run_one(*, use_gpu: bool, label: str, out_subdir: str) -> tuple[float, float, float]:
            cache_dir = RenderService._cache_dir(project.folder_path)
            if os.path.isdir(cache_dir):
                shutil.rmtree(cache_dir, ignore_errors=True)
            os.makedirs(cache_dir, exist_ok=True)

            output_dir = os.path.join(export_root, out_subdir)
            if os.path.isdir(output_dir):
                shutil.rmtree(output_dir, ignore_errors=True)
            os.makedirs(output_dir, exist_ok=True)

            ctx = RenderContext(
                project_path=base_ctx.project_path,
                target_w=base_ctx.target_w,
                target_h=base_ctx.target_h,
                use_gpu=use_gpu,
                enc_v=best_enc.codec_name if use_gpu else "libx264",
            )
            ctx.prefix_keys = RenderService._reusable_prefix_keys(plans)
            cache_jobs = len(episodes) * len(speeds_t)
            compose_jobs = len(plans)
            total_jobs = cache_jobs + compose_jobs
            done = 0

            _safe_print(
                f"\n[bench][{label}] 开始完整渲染测试：《{project.name}》"
                f" 缓存 {len(episodes)} 集 + 合成 {len(plans)} 条",
                flush=True,
            )
            t_all = time.perf_counter()

            # --- 集数缓存 ---
            t_cache0 = time.perf_counter()
            for speed in speeds_t:
                for ep_name in episodes:
                    if should_cancel and should_cancel():
                        raise RenderCancelled("渲染已取消")
                    done += 1
                    if progress_callback:
                        progress_callback(
                            {
                                "phase": "bench_cache",
                                "label": label,
                                "current": done,
                                "total": total_jobs,
                            }
                        )
                    cached = RenderService._ensure_episode_cached(
                        ffmpeg,
                        ffprobe,
                        ctx,
                        ep_name,
                        speed,
                        should_cancel=should_cancel,
                    )
                    if not cached:
                        raise RuntimeError(f"[{label}] 集数缓存失败: {ep_name}")
            cache_sec = time.perf_counter() - t_cache0
            _safe_print(f"[bench][{label}] 缓存完成 {cache_sec:.1f}s", flush=True)

            # --- 成片合成 ---
            t_compose0 = time.perf_counter()
            success = 0
            prefix_dir_ctx = tempfile.TemporaryDirectory(prefix="ae_bench_prefix_")
            try:
                if ctx.prefix_keys:
                    ctx.prefix_dir = prefix_dir_ctx.name
                for i, plan in enumerate(plans):
                    if should_cancel and should_cancel():
                        raise RenderCancelled("渲染已取消")
                    done += 1
                    title = f"bench-{i + 1:02d}"
                    if progress_callback:
                        progress_callback(
                            {
                                "phase": "bench_compose",
                                "label": label,
                                "current": done,
                                "total": total_jobs,
                            }
                        )
                    _safe_print(
                        f"[bench][{label}] 合成 {i + 1}/{len(plans)}: {title}",
                        flush=True,
                    )
                    res = RenderService._render_single(
                        ffmpeg,
                        ffprobe,
                        output_dir,
                        plan,
                        project.name,
                        title,
                        ctx,
                        should_cancel=should_cancel,
                    )
                    ok = res[0] if isinstance(res, tuple) else bool(res)
                    if ok:
                        success += 1
                    elif should_cancel and should_cancel():
                        raise RenderCancelled("渲染已取消")
            finally:
                prefix_dir_ctx.cleanup()
            compose_sec = time.perf_counter() - t_compose0
            total_sec = time.perf_counter() - t_all
            _safe_print(
                f"[bench][{label}] 完成：成功 {success}/{len(plans)} | "
                f"缓存 {cache_sec:.1f}s + 合成 {compose_sec:.1f}s = 合计 {total_sec:.1f}s",
                flush=True,
            )
            return cache_sec, compose_sec, total_sec

        cpu_cache, cpu_compose, cpu_total = _run_one(
            use_gpu=False, label="CPU(libx264)", out_subdir="_bench_cpu"
        )
        gpu_cache = gpu_compose = gpu_total = None
        if cpu_only:
            msg = (
                f"《{project.name}》CPU 渲染速度"
                f"（缓存 {len(episodes)} 集 + 合成 {len(plans)} 条）：\n"
                f"• CPU(libx264)：缓存 {cpu_cache:.1f}s + 合成 {cpu_compose:.1f}s"
                f" = 合计 {cpu_total:.1f}s"
            )
        elif gpu_ok:
            gpu_cache, gpu_compose, gpu_total = _run_one(
                use_gpu=True, label=gpu_label, out_subdir="_bench_gpu"
            )
            ratio = cpu_total / gpu_total if gpu_total and gpu_total > 0 else 0.0
            msg = (
                f"《{project.name}》完整渲染速度对比"
                f"（缓存 {len(episodes)} 集 + 合成 {len(plans)} 条）：\n"
                f"• CPU：缓存 {cpu_cache:.1f}s + 合成 {cpu_compose:.1f}s = 合计 {cpu_total:.1f}s\n"
                f"• {gpu_label}：缓存 {gpu_cache:.1f}s + 合成 {gpu_compose:.1f}s = 合计 {gpu_total:.1f}s\n"
                f"• GPU 合计约比 CPU 快 {ratio:.2f} 倍"
                f"（省时 {max(0.0, cpu_total - gpu_total):.1f}s）"
            )
        else:
            msg = (
                f"《{project.name}》完整渲染速度对比"
                f"（缓存 {len(episodes)} 集 + 合成 {len(plans)} 条）：\n"
                f"• CPU：缓存 {cpu_cache:.1f}s + 合成 {cpu_compose:.1f}s = 合计 {cpu_total:.1f}s\n"
                f"• GPU：不可用（未检测到可用的 NVIDIA / AMD / Intel 硬件加速）"
            )
        _safe_print(f"\n{msg}", flush=True)
        return EncodeBenchmarkResult(
            project_name=project.name,
            episode_count=len(episodes),
            plan_count=len(plans),
            speeds=speeds_t,
            cpu_cache_seconds=cpu_cache,
            cpu_compose_seconds=cpu_compose,
            cpu_total_seconds=cpu_total,
            gpu_cache_seconds=gpu_cache,
            gpu_compose_seconds=gpu_compose,
            gpu_total_seconds=gpu_total,
            gpu_available=gpu_ok,
            message=msg,
        )

    @staticmethod
    def render(
        project: DramaProject,
        *,
        should_cancel: Callable[[], bool] | None = None,
        register_proc: Callable | None = None,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> RenderResult:
        ffmpeg = resolve_ffmpeg()
        ffprobe = resolve_ffprobe()

        project_path = project.folder_path
        from app.common.drama_artifact_paths import locate_production_plan

        plan_path = locate_production_plan(project_path)
        if not plan_path:
            raise FileNotFoundError(f"《{project.name}》未找到 production_plan_v3.json，请先完成策划")

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

        if ctx.use_gpu:
            if ctx.enc_v == "h264_amf":
                enc_label = "GPU(AMD AMF h264_amf quality=speed)"
            elif ctx.enc_v == "h264_qsv":
                enc_label = "GPU(Intel QSV h264_qsv preset=veryfast)"
            else:
                enc_label = f"GPU(NVIDIA NVENC h264_nvenc preset={RenderService._configured_nvenc_preset()})"
        else:
            enc_label = f"CPU(libx264 preset={RenderService._configured_x264_preset()})"
        _safe_print(f"   🎛 编码方式: {enc_label}", flush=True)
        _safe_print(
            f"   📺 输出分辨率: {ctx.target_w}x{ctx.target_h}"
            f"（{RenderService.configured_resolution()}）",
            flush=True,
        )
        t0 = time.perf_counter()

        episodes, speeds = RenderService._collect_episodes_and_speeds(plans)
        if len(speeds) > 1:
            _safe_print(
                f"   ⚠️ 策划方案含多种倍速 {sorted(speeds)}，将分别缓存",
                flush=True,
            )

        _safe_print(
            f"   📦 预处理 {len(episodes)} 集缓存（倍速 {', '.join(str(s) for s in sorted(speeds))}）…",
            flush=True,
        )
        cache_total = len(episodes) * len(speeds)
        cache_done = 0
        t_cache0 = time.perf_counter()
        for speed in sorted(speeds):
            for ep_name in episodes:
                if should_cancel and should_cancel():
                    raise RenderCancelled("渲染已取消")
                cache_done += 1
                if progress_callback:
                    progress_callback(
                        {
                            "phase": "cache",
                            "current": cache_done,
                            "total": cache_total,
                        }
                    )
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
                    raise RuntimeError(
                        f"集数缓存失败: {ep_name}（请确认本机 FFmpeg 可用；"
                        f"显卡不支持或驱动异常时会自动使用 CPU 编码）"
                    )
        cache_sec = time.perf_counter() - t_cache0
        _safe_print(f"   ⏱ 集数缓存耗时: {cache_sec:.1f}s（{enc_label}）", flush=True)

        total = len(plans)
        success_count = 0
        total_video_sec = 0.0
        ctx.prefix_keys = RenderService._reusable_prefix_keys(plans)
        if ctx.prefix_keys:
            _safe_print(
                f"   ♻️ 检测到 {len(ctx.prefix_keys)} 组可复用公共前缀（完整集），将只编码一次",
                flush=True,
            )
        _safe_print(
            f"\n🎬 开始渲染 《{project.name}》：共 {total} 条 -> {output_dir}",
            flush=True,
        )
        if progress_callback:
            progress_callback({"phase": "render", "current": 0, "total": total})

        prefix_dir_ctx = tempfile.TemporaryDirectory(prefix="ae_prefix_")
        try:
            if ctx.prefix_keys:
                ctx.prefix_dir = prefix_dir_ctx.name
            for i, plan in enumerate(plans):
                if should_cancel and should_cancel():
                    raise RenderCancelled("渲染已取消")
                output_title = build_clip_export_filename(project.name, i + 1)
                if progress_callback:
                    progress_callback(
                        {
                            "phase": "render",
                            "current": i + 1,
                            "total": total,
                        }
                    )
                _safe_print(f"   [进度 {i+1}/{total}] 渲染: {output_title}", flush=True)
                t_single0 = time.perf_counter()
                res = RenderService._render_single(
                    ffmpeg,
                    ffprobe,
                    output_dir,
                    plan,
                    project.name,
                    output_title,
                    ctx,
                    **ffmpeg_kwargs,
                )
                ok = res[0] if isinstance(res, tuple) else bool(res)
                duration = res[1] if isinstance(res, tuple) and len(res) > 1 else 0.0
                single_sec = time.perf_counter() - t_single0
                if not ok:
                    if should_cancel and should_cancel():
                        raise RenderCancelled("渲染已取消")
                    _safe_print(f"   [进度 {i+1}/{total}] ❌ 失败/跳过: {output_title} (耗时 {single_sec:.1f}s)", flush=True)
                    continue
                success_count += 1
                total_video_sec += duration
                single_speed = (duration / single_sec) if single_sec > 0.05 and duration > 0 else 0.0
                speed_str = f"{single_speed:.1f}x" if single_speed > 0 else "-"
                _safe_print(
                    f"   [进度 {i+1}/{total}] ✅ 完成: {output_title} "
                    f"(耗时 {single_sec:.1f}s | 片长 {duration:.1f}s | 速度 {speed_str})",
                    flush=True,
                )
        finally:
            prefix_dir_ctx.cleanup()

        total_sec = time.perf_counter() - t0
        compose_sec = max(0.0, total_sec - cache_sec)
        overall_speed = (total_video_sec / total_sec) if total_sec > 0.05 and total_video_sec > 0 else 0.0
        compose_speed = (total_video_sec / compose_sec) if compose_sec > 0.05 and total_video_sec > 0 else 0.0
        avg_single = (compose_sec / success_count) if success_count > 0 else 0.0

        _safe_print(
            "\n"
            "====================================================\n"
            f"🎬 渲染性能统计 - 《{project.name}》\n"
            f"   ▶ 编码引擎: {enc_label}\n"
            f"   ▶ 分辨率:   {ctx.target_w}x{ctx.target_h} ({RenderService.configured_resolution()})\n"
            f"   ▶ 完成情况: {success_count}/{total} 条\n"
            f"   ▶ 成片总长: {total_video_sec:.1f}s ({total_video_sec / 60:.1f}分钟)\n"
            f"   ▶ 预处理缓存: {cache_sec:.1f}s\n"
            f"   ▶ 剪辑合成耗时: {compose_sec:.1f}s (单条平均 {avg_single:.1f}s)\n"
            f"   ▶ 总耗时:   {total_sec:.1f}s\n"
            f"   ⚡ 合成渲染速度: {compose_speed:.1f}x 倍速\n"
            f"   ⚡ 全流程综合速度: {overall_speed:.1f}x 倍速 (含预处理)\n"
            "====================================================\n",
            flush=True,
        )
        return RenderResult(
            output_dir=output_dir,
            success_count=success_count,
            total=total,
            total_seconds=round(total_sec, 2),
            cache_seconds=round(cache_sec, 2),
            compose_seconds=round(compose_sec, 2),
            total_video_seconds=round(total_video_sec, 2),
            speed_ratio=round(compose_speed, 2),
        )

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
        target_w, target_h = RenderService._resolve_target_dims(
            ffprobe, sample_path, orientation
        )
        use_gpu = RenderService._prefer_gpu(ffmpeg)
        if use_gpu:
            enc_info = RenderService._detect_best_encoder(ffmpeg)
            enc_v = enc_info.codec_name if enc_info.is_gpu else "libx264"
        else:
            enc_v = "libx264"
        return RenderContext(
            project_path=project_path,
            target_w=target_w,
            target_h=target_h,
            use_gpu=use_gpu,
            enc_v=enc_v,
        )

    @staticmethod
    def _prefer_gpu(ffmpeg: str) -> bool:
        """是否使用 GPU。可用环境变量强制：AE_FORCE_CPU_ENCODE=1 / AE_FORCE_GPU_ENCODE=1。"""
        force_cpu = os.environ.get("AE_FORCE_CPU_ENCODE", "").strip().lower() in {
            "1", "true", "yes", "on",
        }
        force_gpu = os.environ.get("AE_FORCE_GPU_ENCODE", "").strip().lower() in {
            "1", "true", "yes", "on",
        }
        if force_cpu and force_gpu:
            _safe_print(
                "   ⚠️ 同时设置了 AE_FORCE_CPU_ENCODE 与 AE_FORCE_GPU_ENCODE，以 CPU 为准",
                flush=True,
            )
            return False
        if force_cpu:
            _safe_print("   ℹ️ AE_FORCE_CPU_ENCODE=1，强制使用 CPU 编码", flush=True)
            return False
        if force_gpu:
            _safe_print("   ℹ️ AE_FORCE_GPU_ENCODE=1，强制尝试 GPU 编码", flush=True)
            return True
        return RenderService._detect_best_encoder(ffmpeg).is_gpu

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
        enc_tag: str = "",
    ) -> str:
        stem = os.path.splitext(os.path.basename(episode))[0]
        speed_tag = str(speed).replace(".", "p")
        tag = f"_{enc_tag}" if enc_tag else ""
        name = f"{stem}_spd{speed_tag}_{target_w}x{target_h}{tag}_m{mtime}.mp4"
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
    def _prefix_key(config: dict, speed: float) -> tuple | None:
        """公共前缀标识：完整集列表 + 首集入点 + 倍速。无完整集则无前缀。"""
        full = tuple(config.get("full_episodes") or [])
        if not full:
            return None
        return (
            full,
            float(config.get("first_episode_cut_start", 0) or 0),
            float(speed),
        )

    @staticmethod
    def _reusable_prefix_keys(plans: list) -> set:
        """统计各公共前缀使用次数，返回使用 >= 2 次的前缀 key（值得只编一次）。"""
        counts: dict[tuple, int] = {}
        for plan in plans:
            config = plan.get("files_config") or {}
            key = RenderService._prefix_key(
                config, float(plan.get("global_speed", 1.0))
            )
            if key is not None:
                counts[key] = counts.get(key, 0) + 1
        return {key for key, n in counts.items() if n >= 2}

    @staticmethod
    def _trim_first_episode_continued_card(
        ffmpeg,
        ffprobe,
        ctx: RenderContext,
        segments: list[ClipSegment],
    ) -> list[ClipSegment]:
        """第一集用到片尾且 OCR 命中「未完待续」时，裁掉最后 3 秒。"""
        from app.common.config import cfg
        from app.common.continued_card import (
            covers_tail,
            detect_continued_card,
            is_first_episode,
            trimmed_end,
        )

        if not bool(getattr(cfg.clip_trim_ep1_continued, "value", True)):
            return segments

        out: list[ClipSegment] = []
        for segment in segments:
            if not is_first_episode(segment.episode):
                out.append(segment)
                continue
            src_path = os.path.join(ctx.project_path, segment.episode)
            duration = RenderService._probe_duration(
                ffprobe, src_path, ctx.probe_cache
            )
            if not covers_tail(segment.end, duration):
                out.append(segment)
                continue
            cache_key = os.path.normcase(os.path.abspath(src_path))
            if cache_key not in ctx.continued_card_hits:
                ctx.continued_card_hits[cache_key] = detect_continued_card(
                    ffmpeg, src_path, duration
                )
            if not ctx.continued_card_hits[cache_key]:
                out.append(segment)
                continue
            cut_at = trimmed_end(duration)
            if cut_at <= float(segment.start) + MIN_CUT_DURATION:
                print(
                    f"   ⚠️ 第一集片尾未完待续与入点重叠，跳过该段: {segment.episode}",
                    flush=True,
                )
                continue
            print(
                f"   去掉第一集片尾未完待续: {segment.episode} "
                f"裁至 {cut_at:.1f}s（片长 {duration:.1f}s）",
                flush=True,
            )
            out.append(replace(segment, end=cut_at))
        return out

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
        enc_tag = RenderService._cache_enc_tag(ctx.use_gpu, ctx.enc_v if ctx.use_gpu else "")
        cache_path = RenderService._cache_file_path(
            ctx.project_path,
            episode,
            speed,
            ctx.target_w,
            ctx.target_h,
            mtime,
            enc_tag,
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
        af = (
            "aresample=44100,aformat=channel_layouts=stereo,"
            + build_atempo_filter(speed)
        )

        has_audio = RenderService._has_audio_stream(ffprobe, src_path, ctx.probe_cache)

        def _build_cmd(*, use_gpu: bool) -> list[str]:
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
            codec = ctx.enc_v if use_gpu else None
            cmd.extend(RenderService._video_encode_args(use_gpu=use_gpu, codec=codec))
            cmd.extend(["-c:a", "aac", "-b:a", "128k", cache_path])
            return cmd

        label = f"缓存 {episode}×{speed}"
        attempts = [ctx.use_gpu]
        if ctx.use_gpu:
            attempts.append(False)  # GPU 失败则回退 CPU
        last_err = ""
        for use_gpu in attempts:
            ok, err = RenderService._run_ffmpeg(
                _build_cmd(use_gpu=use_gpu),
                label if use_gpu == ctx.use_gpu else f"{label}(CPU回退)",
                should_cancel=should_cancel,
                register_proc=register_proc,
            )
            if ok:
                break
            last_err = err or "ffmpeg 失败"
            if os.path.exists(cache_path):
                try:
                    os.remove(cache_path)
                except OSError:
                    pass
        else:
            _safe_print(f"❌ {label} 最终失败: {last_err}", flush=True)
            return None

        if not RenderService._validate_output(ffprobe, cache_path, ctx.probe_cache):
            _safe_print(f"⚠️ 缓存产物无效: {cache_path}", flush=True)
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
            proc = win_run(cmd, capture_output=True, text=True, check=True)
            out = proc.stdout.strip()
            if "x" in out:
                w, h = map(int, out.split("x"))
                return "horizontal" if w >= h else "vertical"
        except Exception:
            pass
        return "vertical"

    @staticmethod
    def _scene_scan_window(
        ai_cut_time: float,
        *,
        radius: float = SCENE_SCAN_RADIUS,
    ) -> tuple[float, float]:
        """返回切点扫描窗口 [start, end]（秒），覆盖 tolerance 并留余量。"""
        t = max(0.0, float(ai_cut_time))
        r = max(0.5, float(radius))
        start = max(0.0, t - r)
        end = t + r
        if end <= start:
            end = start + r
        return start, end

    @staticmethod
    def _scene_cache_key(video_path: str, start: float, end: float) -> tuple:
        # 0.1s 量化，便于同一窗口附近的切点复用
        return (video_path, round(start, 1), round(end, 1))

    @staticmethod
    def _get_scene_list(
        video_path: str,
        scene_cache: dict,
        *,
        ai_cut_time: float,
    ) -> list:
        start, end = RenderService._scene_scan_window(ai_cut_time)
        cache_key = RenderService._scene_cache_key(video_path, start, end)
        if cache_key not in scene_cache:
            print(
                f"   切点扫描窗口: {start:.1f}s ~ {end:.1f}s（中心 {float(ai_cut_time):.2f}s）",
                flush=True,
            )
            scene_cache[cache_key] = detect(
                video_path,
                ContentDetector(threshold=27.0),
                start_time=start,
                end_time=end,
                show_progress=False,
            )
        return scene_cache[cache_key]

    @staticmethod
    def _optimize_cut(
        video_path,
        ai_cut_time,
        scene_cache: dict,
        tolerance=1.5,
    ):
        try:
            scene_list = RenderService._get_scene_list(
                video_path, scene_cache, ai_cut_time=float(ai_cut_time)
            )
            nearest = ai_cut_time
            # 台词完整优先：吸附下限 = AI 切点 - 尾垫（即台词结束点），
            # 句中转场不得把切点提前，否则最后一句话会被剪到一半
            floor = ai_cut_time - CUT_SPEECH_PAD_SECONDS
            for scene in scene_list:
                cut = scene[0].get_seconds()
                if cut < floor:
                    continue
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
        scene_cache: dict,
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
            proc = win_run(
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
            proc = win_run(
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
    ) -> tuple[bool, str]:
        """执行 ffmpeg。返回 (是否成功, 失败时的 stderr/说明)。"""
        proc = None
        cmd = RenderService._quiet_ffmpeg_cmd(cmd)
        try:
            _safe_print(f"   ▶ {desc}…", flush=True)
            with tempfile.TemporaryFile(mode="w+b") as stderr_sink:
                proc = win_popen(
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
                        _safe_print(f"⏹ {desc} 已取消", flush=True)
                        return False, "已取消"
                    time.sleep(0.25)
                stderr_sink.seek(0)
                stderr = stderr_sink.read().decode("utf-8", errors="ignore").strip()
                if proc.returncode != 0:
                    if stderr:
                        _safe_print(f"❌ {desc} 失败: {stderr}", flush=True)
                    else:
                        _safe_print(f"❌ {desc} 失败，退出码: {proc.returncode}", flush=True)
                    return False, stderr or f"退出码 {proc.returncode}"
                return True, ""
        except Exception as e:
            _safe_print(f"❌ {desc} 异常: {e}", flush=True)
            return False, str(e)
        finally:
            if register_proc:
                register_proc(None)

    @staticmethod
    def _run_ffmpeg_with_filter_complex(
        base_cmd: list[str],
        filter_graph: str,
        tail_cmd: list[str],
        desc: str,
        **ffmpeg_kwargs,
    ) -> tuple[bool, str]:
        """通过临时脚本传入 filter_complex，避免 Windows 命令行过长 (WinError 206)。"""
        fd, script_path = tempfile.mkstemp(prefix="ae_fc_", suffix=".ffscript")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(filter_graph)
            cmd = [
                *base_cmd,
                "-filter_complex_script",
                script_path,
                *tail_cmd,
            ]
            return RenderService._run_ffmpeg(cmd, desc, **ffmpeg_kwargs)
        finally:
            try:
                os.remove(script_path)
            except OSError:
                pass

    @staticmethod
    def _has_audio_stream(ffprobe, path, probe_cache: dict | None = None) -> bool:
        cache_key = f"has_a:{path}"
        if probe_cache is not None and cache_key in probe_cache:
            return bool(probe_cache[cache_key])
        try:
            proc = win_run(
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
    def _is_gpu_enabled() -> bool:
        """检查配置与环境变量是否允许显卡加速。"""
        from app.common.config import cfg

        force_cpu = os.environ.get("AE_FORCE_CPU_ENCODE", "").strip().lower() in {
            "1", "true", "yes", "on",
        }
        force_gpu = os.environ.get("AE_FORCE_GPU_ENCODE", "").strip().lower() in {
            "1", "true", "yes", "on",
        }
        if force_cpu and force_gpu:
            return False
        if force_cpu:
            return False
        if force_gpu:
            return True

        try:
            return bool(getattr(cfg.encode_enable_gpu, "value", True))
        except Exception:
            return True

    @staticmethod
    def _probe_codec(ffmpeg: str, codec: str) -> bool:
        """真正试编一帧，避免仅因 ffmpeg 编译进了对应编码器就误判硬件可用。"""
        try:
            with tempfile.TemporaryDirectory(prefix="ae_probe_") as td:
                out = os.path.join(td, "probe.mp4")
                probe = win_run(
                    [
                        ffmpeg,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        "color=c=black:s=256x256:d=0.2",
                        "-frames:v",
                        "1",
                        "-c:v",
                        codec,
                        "-f",
                        "mp4",
                        out,
                    ],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                return (
                    probe.returncode == 0
                    and os.path.isfile(out)
                    and os.path.getsize(out) > 0
                )
        except Exception:
            return False

    @staticmethod
    def _detect_best_encoder(
        ffmpeg: str,
        allow_gpu: bool | None = None,
        *,
        use_cache: bool = True,
    ) -> HardwareEncoderInfo:
        """全平台智能探测最优硬件编码器：NVIDIA NVENC -> AMD AMF -> Intel QSV -> CPU libx264。"""
        gpu_enabled = RenderService._is_gpu_enabled() if allow_gpu is None else allow_gpu
        if not gpu_enabled:
            return HardwareEncoderInfo("libx264", "CPU(libx264) [显卡检测已关闭]", is_gpu=False)

        if use_cache and RenderService._cached_hardware_encoder is not None:
            return RenderService._cached_hardware_encoder

        encoder_info: HardwareEncoderInfo | None = None

        # 1. 优先探测 NVIDIA NVENC（通过调用 _has_nvenc 保持已有单元测试 monkeypatch 兼容）
        try:
            if RenderService._has_nvenc(ffmpeg):
                encoder_info = HardwareEncoderInfo("h264_nvenc", "NVIDIA NVENC", is_gpu=True)
        except Exception:
            pass

        # 2. 次选探测 AMD AMF（支持 AMD 独显与 AMD 锐龙 APU 核显）
        if encoder_info is None:
            try:
                if RenderService._probe_codec(ffmpeg, "h264_amf"):
                    encoder_info = HardwareEncoderInfo("h264_amf", "AMD AMF", is_gpu=True)
            except Exception:
                pass

        # 3. 三选探测 Intel QSV（支持 Intel 酷睿核显与 Arc 独显）
        if encoder_info is None:
            try:
                if RenderService._probe_codec(ffmpeg, "h264_qsv"):
                    encoder_info = HardwareEncoderInfo("h264_qsv", "Intel QSV", is_gpu=True)
            except Exception:
                pass

        if encoder_info is None:
            encoder_info = HardwareEncoderInfo("libx264", "CPU(libx264)", is_gpu=False)

        if use_cache:
            RenderService._cached_hardware_encoder = encoder_info
            if encoder_info.is_gpu:
                _safe_print(
                    f"   ℹ️ 首次探测硬件加速：已激活 {encoder_info.vendor_label} ({encoder_info.codec_name})",
                    flush=True,
                )

        return encoder_info

    @staticmethod
    def _has_nvenc(ffmpeg: str) -> bool:
        """真正试编一帧，避免仅因 ffmpeg 编译进了 nvenc 就误判可用。

        注意：分辨率不能太小（如 64x64），否则 NVENC 会报
        “Frame Dimension less than the minimum supported value” 并被误判为不可用。
        """
        try:
            listed = win_run(
                [ffmpeg, "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if "h264_nvenc" not in (listed.stdout or ""):
                return False
            ok = RenderService._probe_codec(ffmpeg, "h264_nvenc")
            if not ok:
                _safe_print("   ℹ️ NVENC 探测不可用，将尝试其他硬件加速", flush=True)
            return ok
        except Exception as exc:
            _safe_print(f"   ℹ️ NVENC 探测异常：{exc}", flush=True)
            return False

    @staticmethod
    def normalize_nvenc_preset(value: str | None) -> str:
        v = (value or _DEFAULT_NVENC_PRESET).strip().lower()
        return v if v in _NVENC_PRESET_SET else _DEFAULT_NVENC_PRESET

    @staticmethod
    def normalize_x264_preset(value: str | None) -> str:
        v = (value or _DEFAULT_X264_PRESET).strip().lower()
        return v if v in _X264_PRESET_SET else _DEFAULT_X264_PRESET

    @staticmethod
    def normalize_amf_preset(value: str | None) -> str:
        v = (value or _DEFAULT_AMF_PRESET).strip().lower()
        return v if v in _AMF_PRESET_SET else _DEFAULT_AMF_PRESET

    @staticmethod
    def normalize_qsv_preset(value: str | None) -> str:
        v = (value or _DEFAULT_QSV_PRESET).strip().lower()
        return v if v in _QSV_PRESET_SET else _DEFAULT_QSV_PRESET

    @staticmethod
    def normalize_render_resolution(value: str | None) -> str:
        v = (value or _DEFAULT_RESOLUTION).strip().lower()
        return v if v in _RESOLUTION_SET else _DEFAULT_RESOLUTION

    @staticmethod
    def configured_resolution() -> str:
        from app.common.config import cfg

        return RenderService.normalize_render_resolution(
            str(cfg.encode_output_resolution.value)
        )

    @staticmethod
    def _probe_source_size(ffprobe, video_path):
        """返回视频 (宽, 高)（偶数化，编码器要求）；探测失败返回 None。"""
        try:
            cmd = [
                ffprobe, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=s=x:p=0",
                video_path,
            ]
            out = win_run(
                cmd, capture_output=True, text=True, check=True
            ).stdout.strip()
            if "x" in out:
                w, h = (int(v) for v in out.split("x")[:2])
                if w > 0 and h > 0:
                    return w - (w % 2), h - (h % 2)
        except Exception:
            pass
        return None

    @staticmethod
    def _resolve_target_dims(ffprobe, sample_path: str, orientation: str) -> tuple[int, int]:
        """按成片分辨率设置解析目标 (宽, 高)。

        720p/1080p：固定档位按画幅方向取尺寸；
        source：探测样片实际尺寸（偶数化），失败回退 720p 档。
        """
        mode = RenderService.configured_resolution()
        if mode == "source":
            size = RenderService._probe_source_size(ffprobe, sample_path)
            if size:
                return size
        dims = _RESOLUTION_DIMS.get(mode, _RESOLUTION_DIMS["720p"])
        return dims["horizontal" if orientation == "horizontal" else "vertical"]

    @staticmethod
    def _configured_nvenc_preset() -> str:
        from app.common.config import cfg

        return RenderService.normalize_nvenc_preset(str(cfg.encode_nvenc_preset.value))

    @staticmethod
    def _configured_x264_preset() -> str:
        from app.common.config import cfg

        return RenderService.normalize_x264_preset(str(cfg.encode_x264_preset.value))

    @staticmethod
    def _configured_amf_preset() -> str:
        from app.common.config import cfg

        return RenderService.normalize_amf_preset(str(cfg.encode_amf_preset.value))

    @staticmethod
    def _configured_qsv_preset() -> str:
        from app.common.config import cfg

        return RenderService.normalize_qsv_preset(str(cfg.encode_qsv_preset.value))

    @staticmethod
    def _cache_enc_tag(use_gpu: bool, codec: str = "") -> str:
        if use_gpu:
            if codec == "h264_amf":
                return f"amf{RenderService._configured_amf_preset()}"
            if codec == "h264_qsv":
                return f"qsv{RenderService._configured_qsv_preset()}"
            return f"nvenc{RenderService._configured_nvenc_preset()}"
        return f"x264{RenderService._configured_x264_preset()}"

    @staticmethod
    def _video_encode_args(*, use_gpu: bool, codec: str | None = None) -> list[str]:
        if not use_gpu:
            preset = RenderService._configured_x264_preset()
            return ["-c:v", "libx264", "-preset", preset, "-crf", "22"]
        c = codec or "h264_nvenc"
        if c == "h264_amf":
            preset = RenderService._configured_amf_preset()
            return ["-c:v", "h264_amf", "-quality", preset, "-rc", "cqp", "-qp_i", "24", "-qp_p", "24"]
        if c == "h264_qsv":
            preset = RenderService._configured_qsv_preset()
            return ["-c:v", "h264_qsv", "-preset", preset, "-global_quality", "24"]
        preset = RenderService._configured_nvenc_preset()
        return ["-c:v", "h264_nvenc", "-preset", preset, "-cq", "24"]

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
    def _overlay_bake_enabled() -> bool:
        from app.common.config import cfg

        try:
            return bool(getattr(cfg.clip_overlay_bake_png, "value", True))
        except Exception:
            return True

    @staticmethod
    def _bake_drawtext_overlay_png(
        ffmpeg,
        ctx: RenderContext,
        drawtext_filters: list[str],
        cache_dir: str,
        ffmpeg_kwargs: dict,
    ) -> str | None:
        """把整串 drawtext（含辉光）预渲成一张全画布透明 PNG。

        用同一 ffmpeg drawtext 引擎渲一次，渲染时只用一次 overlay，
        把几十层辉光 drawtext 的逐帧开销降为 1 次叠加；画质与直接 drawtext 一致。
        """
        if not drawtext_filters:
            return None
        key_src = "|".join([f"{ctx.target_w}x{ctx.target_h}", *drawtext_filters])
        digest = hashlib.sha1(key_src.encode("utf-8")).hexdigest()[:16]
        out_path = os.path.join(cache_dir, f"overlay_{digest}.png")
        if os.path.isfile(out_path) and os.path.getsize(out_path) > 0:
            return out_path

        cmd = [
            ffmpeg,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black@0.0:s={ctx.target_w}x{ctx.target_h},format=rgba",
            "-vf",
            ",".join(drawtext_filters),
            "-frames:v",
            "1",
            "-pix_fmt",
            "rgba",
            out_path,
        ]
        ok, err = RenderService._run_ffmpeg(cmd, "叠字预渲染PNG", **ffmpeg_kwargs)
        if not ok or not (os.path.isfile(out_path) and os.path.getsize(out_path) > 0):
            _safe_print(f"   ⚠️ 叠字预渲染失败，改用 drawtext: {err}", flush=True)
            if os.path.exists(out_path):
                try:
                    os.remove(out_path)
                except OSError:
                    pass
            return None
        return out_path

    @staticmethod
    def _build_compose_graph(
        segments: list[ClipSegment],
        speed: float,
        ctx: RenderContext,
        overlay_filters: list[str],
        image_overlays: list[dict],
        has_outro: bool,
    ) -> str:
        """构建「片段拼接(+可选片尾) + 静态叠字」滤镜图。

        has_outro=False 时用于只含完整集的公共前缀；True 时用于整段或尾部+片尾。
        """
        filter_parts: list[str] = []
        n_main = len(segments)
        for i, segment in enumerate(segments):
            v_trim, a_trim = RenderService._build_trim_filters(segment, speed)
            filter_parts.append(f"[{i}:v]{v_trim}[v{i}];[{i}:a]{a_trim}[a{i}];")

        main_va = "".join(f"[v{i}][a{i}]" for i in range(n_main))
        has_overlay = bool(overlay_filters or image_overlays)

        if has_outro:
            v_outro = (
                f"scale={ctx.target_w}:{ctx.target_h}:force_original_aspect_ratio=decrease,"
                f"pad={ctx.target_w}:{ctx.target_h}:(ow-iw)/2:(oh-ih)/2:black,"
                f"setsar=1"
            )
            a_outro = "aresample=44100,aformat=channel_layouts=stereo"
            outro_idx = n_main
            filter_parts.append(f"[{outro_idx}:v]{v_outro}[vo];")
            filter_parts.append(f"[{outro_idx}:a]{a_outro}[ao];")

        if has_overlay:
            if n_main == 1:
                cur, audio_tag = "[v0]", "[a0]"
            else:
                filter_parts.append(f"{main_va}concat=n={n_main}:v=1:a=1[vm0][am];")
                cur, audio_tag = "[vm0]", "[am]"

            remaining = (1 if overlay_filters else 0) + len(image_overlays)
            step = 0
            if overlay_filters:
                remaining -= 1
                out = "[vm]" if remaining == 0 else f"[od{step}]"
                filter_parts.append(f"{cur}{','.join(overlay_filters)}{out};")
                cur = out
                step += 1

            img_base_idx = n_main + (1 if has_outro else 0)
            for i, spec in enumerate(image_overlays):
                remaining -= 1
                in_tag = f"[{img_base_idx + i}:v]"
                out = "[vm]" if remaining == 0 else f"[od{step}]"
                filter_parts.append(
                    f"{cur}{in_tag}overlay=x={spec['x_expr']}:y={spec['y_expr']}:shortest=1{out};"
                )
                cur = out
                step += 1

            if has_outro:
                filter_parts.append(f"[vm]{audio_tag}[vo][ao]concat=n=2:v=1:a=1[v][a]")
            else:
                filter_parts.append(f"[vm]null[v];{audio_tag}anull[a]")
        elif has_outro:
            filter_parts.append(f"{main_va}[vo][ao]concat=n={n_main + 1}:v=1:a=1[v][a]")
        elif n_main == 1:
            filter_parts.append("[v0]null[v];[a0]anull[a]")
        else:
            filter_parts.append(f"{main_va}concat=n={n_main}:v=1:a=1[v][a]")
        return "".join(filter_parts)

    @staticmethod
    def _render_segments_output(
        ffmpeg,
        ffprobe,
        ctx: RenderContext,
        segments: list[ClipSegment],
        input_paths: list[str],
        speed: float,
        outro_path: str | None,
        overlay_filters: list[str],
        image_overlays: list[dict],
        output_path: str,
        desc: str,
        ffmpeg_kwargs: dict,
    ) -> tuple[bool, str]:
        """把若干片段(+可选片尾)与叠字合成到 output_path；GPU 失败自动回退 CPU。"""
        graph = RenderService._build_compose_graph(
            segments,
            speed,
            ctx,
            overlay_filters,
            image_overlays,
            has_outro=outro_path is not None,
        )
        base_cmd = [ffmpeg, "-y"]
        for p in input_paths:
            base_cmd.extend(["-i", p])
        if outro_path:
            base_cmd.extend(["-i", outro_path])
        for spec in image_overlays:
            base_cmd.extend(["-loop", "1", "-i", spec["path"]])
        map_tail = ["-map", "[v]", "-map", "[a]"]
        gpu_codec = ctx.enc_v if ctx.use_gpu else None
        success, err = RenderService._run_ffmpeg_with_filter_complex(
            base_cmd,
            graph,
            [
                *map_tail,
                *RenderService._video_encode_args(use_gpu=ctx.use_gpu, codec=gpu_codec),
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                output_path,
            ],
            desc,
            **ffmpeg_kwargs,
        )
        if not success and ctx.use_gpu:
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except OSError:
                    pass
            success, err = RenderService._run_ffmpeg_with_filter_complex(
                base_cmd,
                graph,
                [
                    *map_tail,
                    *RenderService._video_encode_args(use_gpu=False),
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    output_path,
                ],
                f"{desc}(CPU回退)",
                **ffmpeg_kwargs,
            )
        return success, err

    @staticmethod
    def _try_prefix_compose(
        ffmpeg,
        ffprobe,
        ctx: RenderContext,
        speed: float,
        prefix_segments: list[ClipSegment],
        prefix_inputs: list[str],
        tail_segments: list[ClipSegment],
        tail_inputs: list[str],
        outro_path: str | None,
        overlay_filters: list[str],
        image_overlays: list[dict],
        output_path: str,
        prefix_key: tuple,
        ffmpeg_kwargs: dict,
    ) -> tuple[bool, float]:
        """公共前缀只编一次，各方案仅编「尾部+片尾」再做流拷贝拼接。

        任一步失败/产物无效则返回 (False, 0.0)，由调用方回退整段合成。
        """
        prefix_path = ctx.prefix_cache.get(prefix_key)
        if not (
            prefix_path
            and os.path.isfile(prefix_path)
            and RenderService._validate_output(ffprobe, prefix_path, ctx.probe_cache)
        ):
            prefix_path = os.path.join(
                ctx.prefix_dir, f"prefix_{len(ctx.prefix_cache)}.mp4"
            )
            ok, err = RenderService._render_segments_output(
                ffmpeg,
                ffprobe,
                ctx,
                prefix_segments,
                prefix_inputs,
                speed,
                None,
                overlay_filters,
                image_overlays,
                prefix_path,
                "公共前缀合成",
                ffmpeg_kwargs,
            )
            if not ok or not RenderService._validate_output(
                ffprobe, prefix_path, ctx.probe_cache
            ):
                _safe_print(f"   ⚠️ 公共前缀渲染失败，回退整段合成: {err}", flush=True)
                if os.path.exists(prefix_path):
                    try:
                        os.remove(prefix_path)
                    except OSError:
                        pass
                return False, 0.0
            ctx.prefix_cache[prefix_key] = prefix_path

        fd, suffix_path = tempfile.mkstemp(
            prefix="ae_suffix_", suffix=".mp4", dir=ctx.prefix_dir
        )
        os.close(fd)
        list_path = suffix_path + ".txt"
        try:
            ok, err = RenderService._render_segments_output(
                ffmpeg,
                ffprobe,
                ctx,
                tail_segments,
                tail_inputs,
                speed,
                outro_path,
                overlay_filters,
                image_overlays,
                suffix_path,
                "尾部+片尾合成",
                ffmpeg_kwargs,
            )
            if not ok:
                _safe_print(f"   ⚠️ 尾部合成失败，回退整段合成: {err}", flush=True)
                return False, 0.0

            expected_dur = (
                RenderService._probe_duration(ffprobe, prefix_path, ctx.probe_cache)
                + RenderService._probe_duration(ffprobe, suffix_path, ctx.probe_cache)
            )

            with open(list_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(f"file '{prefix_path.replace(os.sep, '/')}'\n")
                f.write(f"file '{suffix_path.replace(os.sep, '/')}'\n")
            ok, err = RenderService._run_ffmpeg(
                [
                    ffmpeg,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    list_path,
                    "-c",
                    "copy",
                    output_path,
                ],
                "拼接公共前缀+尾部",
                **ffmpeg_kwargs,
            )
            if not ok:
                _safe_print(f"   ⚠️ 流拷贝拼接失败，回退整段合成: {err}", flush=True)
                if os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                    except OSError:
                        pass
                return False, 0.0
            if not RenderService._validate_output(ffprobe, output_path, ctx.probe_cache):
                _safe_print("   ⚠️ 拼接产物无效，回退整段合成", flush=True)
                if os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                    except OSError:
                        pass
                return False, 0.0
            duration = RenderService._probe_duration(
                ffprobe, output_path, ctx.probe_cache
            )
            # 防流拷贝静默截断：成片时长应与前缀+尾部之和基本一致
            if expected_dur > 0 and duration < expected_dur * 0.8:
                _safe_print(
                    f"   ⚠️ 拼接成片疑似截断（{duration:.1f}s < {expected_dur:.1f}s），回退整段合成",
                    flush=True,
                )
                if os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                    except OSError:
                        pass
                return False, 0.0
            return True, duration
        finally:
            for path in (suffix_path, list_path):
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except OSError:
                    pass

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
    ) -> tuple[bool, float]:
        if should_cancel and should_cancel():
            return False, 0.0
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
            _safe_print(f"⚠️ 找不到片尾素材 {name}，请将文件放入 tools/outro/ 目录")
            return False, 0.0

        last_file = os.path.join(ctx.project_path, config["last_episode"])
        ai_cut_point = config["last_episode_cut_point"]
        _safe_print(f"   分析切点: {output_title}", flush=True)
        cut_point = RenderService._resolve_cut_point(
            ffprobe, last_file, ai_cut_point, ctx.scene_cache
        )
        if cut_point <= 0:
            _safe_print(
                f"⚠️ 无效切点: last_episode_cut_point({ai_cut_point}) "
                f"优化后为 {cut_point}，跳过"
            )
            return False, 0.0
        if cut_point != ai_cut_point:
            _safe_print(f"   切点优化: {ai_cut_point}s -> {cut_point}s")

        all_segments = RenderService.build_segments(config, cut_point)
        if not all_segments:
            _safe_print("⚠️ 无效片段配置，跳过", flush=True)
            return False, 0.0

        # 拆分「完整集公共前缀」与「末集尾部」，分别做未完待续裁剪
        n_full = len(config.get("full_episodes") or [])
        prefix_segments = RenderService._trim_first_episode_continued_card(
            ffmpeg, ffprobe, ctx, all_segments[:n_full]
        )
        tail_segments = RenderService._trim_first_episode_continued_card(
            ffmpeg, ffprobe, ctx, all_segments[n_full:]
        )
        segments = prefix_segments + tail_segments
        if not segments:
            _safe_print("⚠️ 去掉未完待续后无可用片段，跳过", flush=True)
            return False, 0.0

        def _resolve_inputs(segs: list[ClipSegment]) -> list[str] | None:
            paths: list[str] = []
            for segment in segs:
                cached = ctx.episode_cache.get((segment.episode, speed))
                if not cached or not os.path.isfile(cached):
                    _safe_print(f"⚠️ 缺少缓存: {segment.episode}，跳过", flush=True)
                    return None
                paths.append(cached)
            return paths

        prefix_inputs = _resolve_inputs(prefix_segments)
        tail_inputs = _resolve_inputs(tail_segments)
        input_paths = _resolve_inputs(segments)
        if prefix_inputs is None or tail_inputs is None or input_paths is None:
            return False, 0.0

        estimated = sum(
            RenderService._estimate_segment_duration(ffprobe, ctx, seg, speed)
            for seg in segments
        )
        if estimated < MIN_CUT_DURATION:
            _safe_print(
                f"⚠️ 预估成片时长过短（{estimated:.2f}s < {MIN_CUT_DURATION}s），跳过",
                flush=True,
            )
            return False, 0.0

        from app.common.overlay_text_settings import build_overlay_plan

        is_horizontal = ctx.target_w >= ctx.target_h
        cache_dir = RenderService._cache_dir(ctx.project_path)
        overlay_plan = build_overlay_plan(
            project_name,
            horizontal=is_horizontal,
            cache_dir=cache_dir,
            canvas_h=ctx.target_h,
        )
        overlay_filters = overlay_plan["drawtext_filters"]
        image_overlays = [
            spec
            for spec in overlay_plan["image_overlays"]
            if spec.get("path") and os.path.isfile(spec["path"])
        ]

        # 阶段C：辉光等 drawtext 层数较多时，整串预渲成一张全画布 PNG，渲染只用一次 overlay
        if (
            len(overlay_filters) >= OVERLAY_BAKE_MIN_LAYERS
            and RenderService._overlay_bake_enabled()
        ):
            baked_png = RenderService._bake_drawtext_overlay_png(
                ffmpeg, ctx, overlay_filters, cache_dir, ffmpeg_kwargs
            )
            if baked_png:
                image_overlays.insert(
                    0, {"path": baked_png, "x_expr": "0", "y_expr": "0"}
                )
                overlay_filters = []

        # 阶段B：完整集公共前缀复用——前缀只编一次，各方案仅编「尾部+片尾」再流拷贝拼接
        prefix_key = RenderService._prefix_key(config, speed)
        if (
            ctx.prefix_dir
            and prefix_key is not None
            and prefix_key in ctx.prefix_keys
            and prefix_segments
            and tail_segments
        ):
            ok, duration = RenderService._try_prefix_compose(
                ffmpeg,
                ffprobe,
                ctx,
                speed,
                prefix_segments,
                prefix_inputs,
                tail_segments,
                tail_inputs,
                outro_path,
                overlay_filters,
                image_overlays,
                output_path,
                prefix_key,
                ffmpeg_kwargs,
            )
            if ok:
                return True, duration

        # 整段合成（原路径 / 前缀复用的回退）
        gpu_codec = ctx.enc_v if ctx.use_gpu else None
        render_desc = f"合成渲染[{ctx.enc_v}]" if ctx.use_gpu else "合成渲染[CPU]"
        success, err = RenderService._render_segments_output(
            ffmpeg,
            ffprobe,
            ctx,
            segments,
            input_paths,
            speed,
            outro_path,
            overlay_filters,
            image_overlays,
            output_path,
            render_desc,
            ffmpeg_kwargs,
        )
        if not success:
            _safe_print(f"❌ 合成渲染失败: {err}", flush=True)
            return False, 0.0
        if not RenderService._validate_output(ffprobe, output_path, ctx.probe_cache):
            _safe_print(f"⚠️ 成片无效（时长需 >= {MIN_CUT_DURATION}s），跳过", flush=True)
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except OSError:
                    pass
            return False, 0.0
        duration = RenderService._probe_duration(ffprobe, output_path, ctx.probe_cache)
        return True, duration
