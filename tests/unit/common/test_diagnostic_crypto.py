import pytest
from pathlib import Path
from Crypto.PublicKey import RSA

from app.common.diagnostic_crypto import (
    MAGIC_HEADER,
    PUBLIC_KEY_PEM,
    decrypt_diagnostic_payload,
    encrypt_diagnostic_payload,
)

PRIVATE_KEY_PATH = Path("C:/Users/Administrator/Desktop/AE_Diagnostic_Key/private_key.pem")


def test_encryption_and_decryption_roundtrip():
    assert PRIVATE_KEY_PATH.is_file(), "桌面私钥文件应当存在"
    private_pem = PRIVATE_KEY_PATH.read_text(encoding="utf-8")

    sample_data = {
        "error_stage": "render",
        "drama_name": "霸道总裁爱上我",
        "traceback_raw": "Traceback: line 42 in render_video\nRuntimeError: NVENC out of memory",
        "hardware": {"gpu": "RTX 3060", "driver": "535.98"},
        "logs": ["step 1: start", "step 2: ffmpeg -i test.mp4"],
    }

    # 1. 加密
    encrypted_bytes = encrypt_diagnostic_payload(sample_data, PUBLIC_KEY_PEM)
    assert isinstance(encrypted_bytes, bytes)
    assert encrypted_bytes.startswith(MAGIC_HEADER)

    # 确保密文中绝对没有原始明文关键字
    assert b"RTX 3060" not in encrypted_bytes
    assert b"NVENC out of memory" not in encrypted_bytes
    assert b"\xe9\x9c\xb8\xe9\x81\x93\xe6\x80\xbb\xe8\xa3\x81" not in encrypted_bytes  # "霸道总裁" utf-8

    # 2. 解密
    decrypted_data = decrypt_diagnostic_payload(encrypted_bytes, private_pem)
    assert decrypted_data == sample_data
    assert decrypted_data["drama_name"] == "霸道总裁爱上我"
    assert "NVENC out of memory" in decrypted_data["traceback_raw"]


def test_tampered_payload_fails():
    private_pem = PRIVATE_KEY_PATH.read_text(encoding="utf-8")
    sample_data = {"test": 123}

    encrypted_bytes = encrypt_diagnostic_payload(sample_data, PUBLIC_KEY_PEM)

    # 非法魔数
    with pytest.raises(ValueError, match="魔数校验失败"):
        decrypt_diagnostic_payload(b"BADMAGIC" + encrypted_bytes[8:], private_pem)

    # 篡改密文字节
    tampered = bytearray(encrypted_bytes)
    tampered[-1] ^= 0xFF
    with pytest.raises(Exception):
        decrypt_diagnostic_payload(bytes(tampered), private_pem)
