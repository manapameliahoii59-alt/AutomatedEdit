import base64
import json

from Crypto.Cipher import AES

from app.common.plan_crypto import decrypt_plan_payload


def test_decrypt_plan_payload():
    key = "0123456789abcdef" * 4
    nonce = b"\x01" * 12
    plaintext = json.dumps([{"title": "x"}], ensure_ascii=False).encode("utf-8")
    cipher = AES.new(bytes.fromhex(key), AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)
    blob = ciphertext + tag
    restored = decrypt_plan_payload(
        key,
        base64.b64encode(blob).decode("ascii"),
        base64.b64encode(nonce).decode("ascii"),
    )
    assert restored == [{"title": "x"}]
