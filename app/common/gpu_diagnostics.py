import subprocess

from app.common.ffmpeg_paths import resolve_ffmpeg


def _ffmpeg_has_nvenc(ffmpeg: str) -> bool:
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


def _test_nvenc_encode(ffmpeg: str) -> bool:
    try:
        proc = subprocess.run(
            [
                ffmpeg, "-y",
                "-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.1",
                "-c:v", "h264_nvenc",
                "-f", "null", "-",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return proc.returncode == 0
    except Exception:
        return False


def _query_nvidia_smi() -> str:
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except Exception:
        pass
    return "未检测到（nvidia-smi 不可用）"


def run_gpu_diagnostics() -> str:
    lines = ["【系统显卡】", _query_nvidia_smi(), ""]

    lines.append("【PyTorch / 识别】")
    try:
        import torch
        lines.append(f"PyTorch 版本：{torch.__version__}")
        if torch.cuda.is_available():
            lines.append("CUDA 可用：是")
            lines.append(f"设备：{torch.cuda.get_device_name(0)}")
            lines.append(f"CUDA 版本：{torch.version.cuda}")
        else:
            lines.append("CUDA 可用：否（识别将使用 CPU）")
    except Exception as e:
        lines.append(f"PyTorch 加载失败：{e}")

    lines.append("")
    lines.append("【FFmpeg / 渲染】")
    try:
        ffmpeg = resolve_ffmpeg()
        lines.append(f"FFmpeg：{ffmpeg}")
        has_nvenc = _ffmpeg_has_nvenc(ffmpeg)
        lines.append(f"h264_nvenc 编码器：{'已列出' if has_nvenc else '未找到'}")
        if has_nvenc:
            ok = _test_nvenc_encode(ffmpeg)
            lines.append(f"NVENC 实测编码：{'成功' if ok else '失败'}")
            if ok:
                lines.append("说明：最终合成可使用 GPU 加速（预切割仍为 CPU）")
            else:
                lines.append("说明：编码器存在但实测失败，请检查驱动或改用 CPU 渲染")
        else:
            lines.append("说明：渲染将使用 CPU（libx264）")
    except Exception as e:
        lines.append(f"FFmpeg 检测失败：{e}")

    return "\n".join(lines)
