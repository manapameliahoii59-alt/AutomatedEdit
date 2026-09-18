"""桌面端机器信息采集（CPU / 显卡 / 内存；Windows 原生，无第三方依赖）。"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import socket
import sys
import uuid
from typing import Any

from app.common.config import VERSION
from app.common.win_subprocess import run as win_run


class _MemoryStatusEx(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _cpu_name() -> str:
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        )
        try:
            value, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            name = str(value or "").strip()
            if name:
                return name
        finally:
            winreg.CloseKey(key)
    except Exception:
        pass
    return str(platform.processor() or "").strip()


def _physical_cores() -> int:
    try:
        proc = win_run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "(Get-CimInstance Win32_Processor | "
                "Measure-Object -Property NumberOfCores -Sum).Sum",
            ],
            capture_output=True,
            text=True,
            timeout=25,
        )
        text = (proc.stdout or "").strip()
        if text:
            return max(0, _to_int(text))
    except Exception:
        pass
    return 0


def _memory_mb() -> tuple[int, int]:
    try:
        status = _MemoryStatusEx()
        status.dwLength = ctypes.sizeof(_MemoryStatusEx)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            total = int(status.ullTotalPhys) // (1024 * 1024)
            available = int(status.ullAvailPhys) // (1024 * 1024)
            return max(0, total), max(0, available)
    except Exception:
        pass
    return 0, 0


def _vendor_from_name(name: str) -> str:
    lowered = name.lower()
    if "nvidia" in lowered:
        return "NVIDIA"
    if "amd" in lowered or "radeon" in lowered:
        return "AMD"
    if "intel" in lowered:
        return "Intel"
    return ""


_VIRTUAL_DISPLAY_KEYWORDS = (
    "virtual",
    "remote",
    "microsoft basic",
    "gameviewer",
    "todesk",
    "sunlogin",
    "oray",
    "parsec",
    "displaylink",
)


def _is_virtual_display(name: str) -> bool:
    lowered = name.lower()
    return any(keyword in lowered for keyword in _VIRTUAL_DISPLAY_KEYWORDS)


def _nvidia_gpus() -> list[dict[str, Any]]:
    try:
        proc = win_run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            return []
        gpus: list[dict[str, Any]] = []
        for line in (proc.stdout or "").splitlines():
            parts = [part.strip() for part in line.split(",")]
            if not parts or not parts[0]:
                continue
            gpus.append(
                {
                    "name": parts[0],
                    "vendor": "NVIDIA",
                    "vram_mb": _to_int(parts[1]) if len(parts) > 1 else 0,
                    "driver": parts[2] if len(parts) > 2 else "",
                }
            )
        return gpus
    except Exception:
        return []


def _windows_gpus() -> list[dict[str, Any]]:
    try:
        proc = win_run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "Get-CimInstance Win32_VideoController | "
                "Select-Object Name,AdapterRAM | ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            timeout=25,
        )
        text = (proc.stdout or "").strip()
        if not text:
            return []
        data = json.loads(text)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return []
        gpus: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            name = str(item.get("Name") or "").strip()
            if not name or _is_virtual_display(name):
                continue
            vram_mb = 0
            ram = item.get("AdapterRAM")
            if ram:
                vram_mb = max(0, _to_int(ram) // (1024 * 1024))
            gpus.append(
                {
                    "name": name,
                    "vendor": _vendor_from_name(name),
                    "vram_mb": vram_mb,
                    "driver": "",
                }
            )
        return gpus
    except Exception:
        return []


def _collect_gpus() -> list[dict[str, Any]]:
    gpus = _nvidia_gpus()
    seen = {str(gpu.get("name") or "").lower() for gpu in gpus}
    for gpu in _windows_gpus():
        key = str(gpu.get("name") or "").lower()
        if key and key not in seen:
            gpus.append(gpu)
            seen.add(key)

    if not gpus:
        torch = sys.modules.get("torch")
        if torch is not None:
            try:
                if torch.cuda.is_available():
                    gpus.append(
                        {
                            "name": torch.cuda.get_device_name(0),
                            "vendor": "NVIDIA",
                            "vram_mb": 0,
                            "driver": "",
                        }
                    )
            except Exception:
                pass
    return gpus


_CACHED_MACHINE_ID: str | None = None


def _machine_id() -> str:
    global _CACHED_MACHINE_ID
    if _CACHED_MACHINE_ID:
        return _CACHED_MACHINE_ID

    # 1. 尝试主板 BIOS UUID（硬件物理唯一标识）
    try:
        proc = win_run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "(Get-CimInstance Win32_ComputerSystemProduct).UUID",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        val = (proc.stdout or "").strip()
        clean = val.replace("-", "").strip()
        if (
            val
            and len(clean) >= 16
            and not set(clean).issubset({"0"})
            and not set(clean).issubset({"F", "f"})
            and clean.lower() != "none"
        ):
            _CACHED_MACHINE_ID = val[:64]
            return _CACHED_MACHINE_ID
    except Exception:
        pass

    # 2. 回退 Windows 注册表 MachineGuid
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        )
        try:
            val, _ = winreg.QueryValueEx(key, "MachineGuid")
            s = str(val or "").strip()
            if s:
                _CACHED_MACHINE_ID = s[:64]
                return _CACHED_MACHINE_ID
        finally:
            winreg.CloseKey(key)
    except Exception:
        pass

    # 3. 回退 MAC 节点地址
    try:
        node = uuid.getnode()
        if node:
            _CACHED_MACHINE_ID = f"{node:012x}"
            return _CACHED_MACHINE_ID
    except Exception:
        pass

    return ""


def _local_ips() -> str:
    ips: list[str] = []
    # 优先探测默认出网路由网卡的本地 IP
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("223.5.5.5", 80))
            primary = s.getsockname()[0]
            if primary and not primary.startswith("127."):
                ips.append(primary)
    except Exception:
        pass

    # 补充其它非回环、非链路本地网卡 IP
    try:
        hostname = socket.gethostname()
        _, _, host_ips = socket.gethostbyname_ex(hostname)
        for ip in host_ips:
            if (
                ip
                and not ip.startswith("127.")
                and not ip.startswith("169.254.")
                and ip not in ips
            ):
                ips.append(ip)
    except Exception:
        pass

    return ", ".join(ips)[:128]


def collect_machine_info() -> dict[str, Any]:
    """采集机器信息；任何一项失败都返回可用的部分，绝不抛异常。"""
    ram_total_mb, ram_available_mb = _memory_mb()
    gpus = _collect_gpus()
    logical_cores = os.cpu_count() or 0
    physical_cores = _physical_cores()
    return {
        "os": str(platform.platform() or "")[:255],
        "hostname": str(platform.node() or "")[:128],
        "machine_id": _machine_id()[:64],
        "local_ip": _local_ips()[:128],
        "cpu_name": _cpu_name()[:255],
        "cpu_cores_logical": max(0, logical_cores),
        "cpu_cores_physical": max(0, physical_cores),
        "ram_total_mb": ram_total_mb,
        "ram_available_mb": ram_available_mb,
        "gpus": gpus[:8],
        "gpu_summary": "; ".join(
            str(gpu.get("name") or "") for gpu in gpus if gpu.get("name")
        )[:1024],
        "client_version": VERSION,
    }
