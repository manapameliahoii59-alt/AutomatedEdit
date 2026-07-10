"""策划结果加密（AES-GCM，按用户密钥）。"""

from __future__ import annotations

import base64
import json
import secrets
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def generate_plan_decrypt_key() -> str:
    """32 字节密钥，hex 编码（64 字符）。"""
    return secrets.token_hex(32)


def _decode_key(hex_key: str) -> bytes:
    key = (hex_key or "").strip()
    if len(key) != 64:
        raise ValueError("无效的策划解密密钥")
    return bytes.fromhex(key)


def encrypt_plan_payload(hex_key: str, payload: Any) -> dict[str, str]:
    key = _decode_key(hex_key)
    nonce = secrets.token_bytes(12)
    plaintext = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return {
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "key_id": "default",
    }


def decrypt_plan_payload(hex_key: str, ciphertext_b64: str, nonce_b64: str) -> Any:
    key = _decode_key(hex_key)
    ciphertext = base64.b64decode(ciphertext_b64)
    nonce = base64.b64decode(nonce_b64)
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    return json.loads(plaintext.decode("utf-8"))
