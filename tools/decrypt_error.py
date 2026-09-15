"""开发者本地专属：诊断文件解密与可视化工具。

支持解密由客户端生成的 error.aedump 与 crash.aedump 加密文件。
私钥默认优先读取: Desktop/AE_Diagnostic_Key/private_key.pem
"""

from __future__ import annotations

import datetime
import json
import os
import sys
from pathlib import Path

# 添加项目根目录到 sys.path 以便直接运行
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.common.diagnostic_crypto import decrypt_diagnostic_payload


def _find_private_key() -> Path | None:
    """按优先级寻找私钥文件。"""
    candidates = [
        # 1. 桌面专属文件夹
        Path.home() / "Desktop" / "AE_Diagnostic_Key" / "private_key.pem",
        Path("C:/Users/Administrator/Desktop/AE_Diagnostic_Key/private_key.pem"),
        # 2. 桌面根目录
        Path.home() / "Desktop" / "private_key.pem",
        # 3. 本地 tools/keys/ 目录
        PROJECT_ROOT / "tools" / "keys" / "private_key.pem",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def main() -> int:
    if len(sys.argv) < 2:
        print("=" * 70)
        print("使用方式:")
        print("  1. 直接鼠标拖拽 .aedump 文件到【一键解密诊断包.bat】图标上；")
        print("  2. 或在命令行运行: python tools/decrypt_error.py <path_to_aedump>")
        print("=" * 70)
        return 1

    dump_path = Path(sys.argv[1]).resolve()
    if not dump_path.is_file():
        print(f"❌ 错误：指定的文件不存在: {dump_path}")
        return 1

    key_path = _find_private_key()
    if not key_path:
        print("❌ 错误：未找到私钥文件！")
        print("请检查桌面是否存在文件夹: Desktop\\AE_Diagnostic_Key\\private_key.pem")
        return 1

    try:
        private_pem = key_path.read_text(encoding="utf-8")
        payload = dump_path.read_bytes()
        report = decrypt_diagnostic_payload(payload, private_pem)
    except Exception as e:
        print(f"❌ 解密失败: {e}")
        return 1

    # 打印格式化诊断看板
    print("\n" + "=" * 75)
    print("           【AutomatedEdit 客户端技术诊断解密报告】")
    print("=" * 75)
    print(f"报告生成时间: {report.get('report_time')}  |  客户端版本: {report.get('app_version')}")
    print(f"故障处理阶段: {report.get('stage')}  |  涉及剧目: 《{report.get('drama_name') or '未指定'}》")
    print(f"用户界面提示: {report.get('friendly_msg')}")
    print(f"运行环境类型: {'打包运行环境 (Nuitka Frozen)' if report.get('is_frozen') else '源码开发环境'}")

    sys_info = report.get("system", {})
    print("-" * 75)
    print(f"【系统配置】: {sys_info.get('os')} (Python {sys_info.get('python')})")
    print(f"【CPU/处理器】: {sys_info.get('processor') or '未知'}")

    gpu = report.get("gpu", {})
    print(f"【显卡设备】: {gpu.get('gpu_name')}")
    print(f"【显卡驱动】: {gpu.get('driver_version')}  |  CUDA 可用: {gpu.get('cuda_available')} (版本: {gpu.get('cuda_version')})")

    disks = report.get("disk", {})
    disk_str = "  ".join([f"{k}: {v}GB" for k, v in disks.items()])
    print(f"【磁盘空间】: {disk_str or '未获取'}")

    print("=" * 75)
    print("【核心真实堆栈 (Raw Traceback)】:")
    print("-" * 75)
    print(report.get("traceback_raw", "无堆栈信息"))

    recent_logs = report.get("recent_logs", [])
    print("=" * 75)
    print(f"【崩溃/报错前最近 {len(recent_logs)} 步运行日志轨迹 (Recent Logs)】:")
    print("-" * 75)
    if recent_logs:
        for line in recent_logs:
            print(f"  {line}")
    else:
        print("  (无前置日志记录)")
    print("=" * 75)

    # 同步保存明文文本报告
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_txt = dump_path.parent / f"{dump_path.stem}_decrypted_{ts}.txt"
    try:
        with open(out_txt, "w", encoding="utf-8") as f:
            f.write(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"\n✅ 完整明文 JSON 报告已保存至: {out_txt}")
    except Exception:
        pass

    print("\n[私钥位置]: " + str(key_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
