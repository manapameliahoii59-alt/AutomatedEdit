"""诊断数据混合加密与解密封包引擎。

- 客户端：仅内置 PUBLIC_KEY_PEM（公钥），仅能加密，无法解密。
- 开发者机：持有 PRIVATE_KEY_PEM（私钥），可解密提取原始诊断 JSON。
"""

from __future__ import annotations

import json
from Crypto.Cipher import AES, PKCS1_OAEP
from Crypto.PublicKey import RSA
from Crypto.Random import get_random_bytes

MAGIC_HEADER = b"AEDUMP01"

# 客户端内置固化公钥（RSA-2048）
PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEApTqbiF4XHJeh/62zdQtk
9S/3DNKvMl52py7y2oONYm2IM8Td8tyDC69AAg55BQx+nackjfKl2jTzx8yW23hk
DWLyecZOfz8d4LYfj5ouxFNgay2gx7GGg9g3rt/Y9Gsq8wPjapiiPvYjVYiI+MWf
sglkaY3i5QcHCp2KaC2vm2rB/TvneHkFQEFTsSECef0rZPsE2sjOYhurKbC5KJDI
7cwxALBDR/3k9blYVOIJiHVWrwfcC52+H53ophDg1UYwFLV4OOvtgX3/euGr65IW
Qo4wtLrSFZfUtobo+vDgcjtHwrUAlnJtntj6HQXwM36yvh+Gbd0oNZ2CxK+DTRUO
rwIDAQAB
-----END PUBLIC KEY-----"""


def encrypt_diagnostic_payload(data: dict, public_key_pem: str = PUBLIC_KEY_PEM) -> bytes:
    """将诊断字典使用 RSA-2048 + AES-256-GCM 混合加密为单一字节流。

    封包结构:
    [8B MAGIC: b"AEDUMP01"]
    [2B KEY_LEN (big-endian)]
    [KEY_LEN B RSA-Encrypted AES Key]
    [12B Nonce]
    [16B Tag]
    [Ciphertext]
    """
    raw_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")

    # 1. 生成一次性 AES-256 密钥与 12 字节 Nonce
    aes_key = get_random_bytes(32)
    nonce = get_random_bytes(12)

    # 2. 用 AES-GCM 加密业务数据
    cipher_aes = AES.new(aes_key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher_aes.encrypt_and_digest(raw_bytes)

    # 3. 用 RSA 公钥加密 AES 密钥
    rsa_key = RSA.import_key(public_key_pem)
    cipher_rsa = PKCS1_OAEP.new(rsa_key)
    enc_aes_key = cipher_rsa.encrypt(aes_key)

    # 4. 二进制组包
    key_len = len(enc_aes_key)
    return MAGIC_HEADER + key_len.to_bytes(2, "big") + enc_aes_key + nonce + tag + ciphertext


def decrypt_diagnostic_payload(payload_bytes: bytes, private_key_pem: str) -> dict:
    """【仅开发者本地调用】使用私钥解密 .aedump 字节流，还原原始 JSON 字典。"""
    if not payload_bytes.startswith(MAGIC_HEADER):
        raise ValueError("非法的诊断文件格式或文件已损坏 (魔数校验失败)")

    offset = len(MAGIC_HEADER)
    key_len = int.from_bytes(payload_bytes[offset : offset + 2], "big")
    offset += 2

    enc_aes_key = payload_bytes[offset : offset + key_len]
    offset += key_len

    nonce = payload_bytes[offset : offset + 12]
    offset += 12

    tag = payload_bytes[offset : offset + 16]
    offset += 16

    ciphertext = payload_bytes[offset:]

    # 1. 用私钥解密出 AES-256 密钥
    rsa_key = RSA.import_key(private_key_pem)
    cipher_rsa = PKCS1_OAEP.new(rsa_key)
    aes_key = cipher_rsa.decrypt(enc_aes_key)

    # 2. 用 AES 密钥解密数据并验证 Tag
    cipher_aes = AES.new(aes_key, AES.MODE_GCM, nonce=nonce)
    decrypted_bytes = cipher_aes.decrypt_and_verify(ciphertext, tag)

    return json.loads(decrypted_bytes.decode("utf-8"))
