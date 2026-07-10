import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.services.plan_crypto import decrypt_plan_payload, encrypt_plan_payload, generate_plan_decrypt_key


def test_encrypt_decrypt_roundtrip():
    key = generate_plan_decrypt_key()
    payload = [{"title": "demo-0708-01", "hook": "测试"}]
    encrypted = encrypt_plan_payload(key, payload)
    restored = decrypt_plan_payload(key, encrypted["ciphertext"], encrypted["nonce"])
    assert restored == payload


def test_client_pycryptodome_compatible():
    """客户端使用 pycryptodome 解密服务端 cryptography 密文。"""
    import base64
    import json

    from Crypto.Cipher import AES

    key = generate_plan_decrypt_key()
    encrypted = encrypt_plan_payload(key, [{"ok": True}])
    blob = base64.b64decode(encrypted["ciphertext"])
    nonce = base64.b64decode(encrypted["nonce"])
    tag = blob[-16:]
    ciphertext = blob[:-16]
    cipher = AES.new(bytes.fromhex(key), AES.MODE_GCM, nonce=nonce)
    plaintext = cipher.decrypt_and_verify(ciphertext, tag)
    assert json.loads(plaintext.decode("utf-8")) == [{"ok": True}]
