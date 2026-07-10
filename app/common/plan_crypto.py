"""策划结果解密（与服务端 plan_crypto 配套）。"""

from __future__ import annotations

import base64
import json
from typing import Any

from Crypto.Cipher import AES


def _decode_key(hex_key: str) -> bytes:
    key = (hex_key or "").strip()
    if len(key) != 64:
        raise ValueError("未配置策划解密密钥，请重新登录")
    return bytes.fromhex(key)


def decrypt_plan_payload(hex_key: str, ciphertext_b64: str, nonce_b64: str) -> Any:
    key = _decode_key(hex_key)
    blob = base64.b64decode(ciphertext_b64)
    nonce = base64.b64decode(nonce_b64)
    tag = blob[-16:]
    ciphertext = blob[:-16]
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    plaintext = cipher.decrypt_and_verify(ciphertext, tag)
    return json.loads(plaintext.decode("utf-8"))
