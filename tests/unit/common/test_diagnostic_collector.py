import os
from pathlib import Path
from app.common.diagnostic_collector import build_diagnostic_package, save_encrypted_error_dump
from app.common.diagnostic_crypto import decrypt_diagnostic_payload
from app.common.log_ring_buffer import LogRingBuffer

PRIVATE_KEY_PATH = Path("C:/Users/Administrator/Desktop/AE_Diagnostic_Key/private_key.pem")


def test_collector_and_dump(tmp_path):
    LogRingBuffer.clear()
    LogRingBuffer.append("2026-09-15 10:00:00 [DEBUG] 测试步骤 1: 准备工作完成")
    LogRingBuffer.append("2026-09-15 10:00:01 [DEBUG] 测试步骤 2: 发起 FFmpeg 编码")

    try:
        raise RuntimeError("模拟渲染核心错误: NVENC driver crash")
    except RuntimeError as exc:
        err = exc

    # 1. 采集数据包
    data = build_diagnostic_package(
        raw_error=err,
        stage="render",
        drama_name="重生之我是修仙大佬",
        friendly_msg="视频渲染合成失败，请检查文件后重试",
    )

    assert data["stage"] == "render"
    assert data["drama_name"] == "重生之我是修仙大佬"
    assert "NVENC driver crash" in data["traceback_raw"]
    assert len(data["recent_logs"]) >= 2
    assert "测试步骤 1" in data["recent_logs"][0]

    # 2. 静默落盘测试
    test_dump_file = "test_error.aedump"
    saved_path = save_encrypted_error_dump(
        raw_error=err,
        stage="render",
        drama_name="重生之我是修仙大佬",
        friendly_msg="视频渲染合成失败，请检查文件后重试",
        target_filename=test_dump_file,
    )

    assert os.path.isfile(saved_path)

    # 验证直接读为密文
    raw_content = Path(saved_path).read_bytes()
    assert b"NVENC driver crash" not in raw_content
    assert b"AEDUMP01" in raw_content

    # 3. 使用私钥解密测试
    private_pem = PRIVATE_KEY_PATH.read_text(encoding="utf-8")
    decrypted = decrypt_diagnostic_payload(raw_content, private_pem)
    assert decrypted["drama_name"] == "重生之我是修仙大佬"
    assert "NVENC driver crash" in decrypted["traceback_raw"]
    assert "测试步骤 2" in decrypted["recent_logs"][-1]

    # 清理
    try:
        os.remove(saved_path)
    except Exception:
        pass
