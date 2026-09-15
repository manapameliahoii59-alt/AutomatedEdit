"""诊断数据采集器：采集软硬件环境、未脱敏堆栈、磁盘空间与前置日志并静默加密落盘。"""

from __future__ import annotations

import datetime
import os
import platform
import shutil
import sys
import traceback
from typing import Any

from app.common.config import VERSION
from app.common.diagnostic_crypto import encrypt_diagnostic_payload
from app.common.log_ring_buffer import LogRingBuffer


def _get_gpu_and_cuda_summary() -> dict:
    """采集显卡与驱动信息。"""
    info = {
        "gpu_name": "未检测到或无独立显卡",
        "driver_version": "未知",
        "cuda_available": False,
        "cuda_version": "未知",
    }
    torch = sys.modules.get("torch")
    if torch is not None:
        try:
            cuda_ok = bool(torch.cuda.is_available())
            info["cuda_available"] = cuda_ok
            if cuda_ok:
                info["gpu_name"] = str(torch.cuda.get_device_name(0))
                info["cuda_version"] = str(getattr(torch.version, "cuda", "未知"))
        except Exception:
            pass

    # 尝试通过 nvidia-smi 提取精确驱动版本
    try:
        from app.common.win_subprocess import run as win_run

        proc = win_run(
            ["nvidia-smi", "--query-gpu=driver_version,gpu_name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            parts = proc.stdout.strip().split(",")
            info["driver_version"] = parts[0].strip()
            if len(parts) > 1 and info["gpu_name"] == "未检测到或无独立显卡":
                info["gpu_name"] = parts[1].strip()
    except Exception:
        pass
    return info


def _get_disk_space_summary() -> dict:
    """采集关键磁盘剩余空间。"""
    disks = {}
    try:
        c_usage = shutil.disk_usage("C:\\")
        disks["C_free_gb"] = round(c_usage.free / (1024**3), 2)
        disks["C_total_gb"] = round(c_usage.total / (1024**3), 2)
    except Exception:
        pass

    try:
        from app.common.config import cfg

        export_dir = cfg.clip_export_dir.value
        if export_dir and os.path.exists(export_dir):
            e_usage = shutil.disk_usage(export_dir)
            drive_letter = os.path.splitdrive(export_dir)[0] or "export_dir"
            disks[f"{drive_letter}_free_gb"] = round(e_usage.free / (1024**3), 2)
    except Exception:
        pass
    return disks


def build_diagnostic_package(
    raw_error: Any,
    stage: str = "general",
    drama_name: str = "",
    friendly_msg: str = "",
) -> dict:
    """组装最详尽的技术诊断包字典。"""
    raw_tb = ""
    if isinstance(raw_error, BaseException):
        if raw_error.__traceback__:
            raw_tb = "".join(traceback.format_exception(type(raw_error), raw_error, raw_error.__traceback__)).strip()
        else:
            raw_tb = f"{type(raw_error).__name__}: {raw_error}"
    elif raw_error:
        raw_tb = str(raw_error).strip()

    # 如果有当前栈活跃 traceback 且未包含，则一并捕获
    cur_exc = traceback.format_exc()
    if cur_exc and "NoneType: None" not in cur_exc and cur_exc.strip() not in raw_tb:
        raw_tb = f"{raw_tb}\n\n[Active Traceback]:\n{cur_exc}".strip()

    if not raw_tb:
        raw_tb = "无活跃堆栈"

    return {
        "report_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "app_version": VERSION,
        "is_frozen": getattr(sys, "frozen", False) or getattr(sys.modules.get("__main__"), "__compiled__", False),
        "stage": stage,
        "drama_name": drama_name,
        "friendly_msg": friendly_msg,
        "system": {
            "os": platform.platform(),
            "python": platform.python_version(),
            "processor": platform.processor(),
            "app_dir": os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        },
        "gpu": _get_gpu_and_cuda_summary(),
        "disk": _get_disk_space_summary(),
        "traceback_raw": raw_tb,
        "recent_logs": LogRingBuffer.get_recent_logs(200),
    }


def save_encrypted_error_dump(
    raw_error: Any,
    stage: str = "general",
    drama_name: str = "",
    friendly_msg: str = "",
    target_filename: str = "error.aedump",
) -> str:
    """静默加密写入 logs 目录（默认 logs/error.aedump）。失败时静默，决不影响主业务。"""
    try:
        data = build_diagnostic_package(raw_error, stage, drama_name, friendly_msg)
        enc_bytes = encrypt_diagnostic_payload(data)

        log_dir = os.path.abspath("logs")
        os.makedirs(log_dir, exist_ok=True)
        target_path = os.path.join(log_dir, target_filename)

        with open(target_path, "wb") as f:
            f.write(enc_bytes)
        return target_path
    except Exception:
        return ""
