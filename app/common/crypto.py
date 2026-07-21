import builtins
import json

from app.common.aes import aes_encrypt, aes_decrypt
from app.common.my_logger import my_logger as logger

ENCRYPTION_MARKER = "ENC:"


def _is_bundled() -> bool:
    return getattr(builtins, '__compiled__', False)


def encrypt_file(filepath: str):
    with open(filepath, "r", encoding="utf-8") as f:
        plaintext = f.read()
    encrypted = aes_encrypt(plaintext)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(ENCRYPTION_MARKER + encrypted)


def read_json(filepath: str) -> dict | list:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    if content.startswith(ENCRYPTION_MARKER):
        encrypted = content[len(ENCRYPTION_MARKER):]
        decrypted = aes_decrypt(encrypted)
        if not decrypted:
            raise RuntimeError(f"文件解密失败: {filepath}")
        return json.loads(decrypted)
    return json.loads(content)


def write_encrypted_json(filepath: str, data):
    from app.common.drama_artifact_paths import ensure_path_writable

    ensure_path_writable(filepath)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if _is_bundled():
        ensure_path_writable(filepath)
        encrypt_file(filepath)
