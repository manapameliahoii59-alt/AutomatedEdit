"""发布链路自检：一条命令验完客户端更新下载的完整通路。

用法（在 server/ 目录下）：
    python scripts/check_release_url.py

检查项：
    1. version.json 能被正确读取（latest / min_supported / download_url）
    2. COS 预签名是否启用，签名链接是否生成
    3. 签名链接能否下载（HTTP 200 + 文件头 MZ）
    4. 裸链是否已被拒绝（私有桶应为 403）
    5. 文件大小是否与本地安装包一致（本地存在时才比对）

退出码：0 全部通过；1 存在失败项。
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

from app.config import settings  # noqa: E402
from app.services import cos_presign  # noqa: E402
from app.services.client_version import build_client_version_out  # noqa: E402

TIMEOUT = (15, 60)
OK = "  [OK]  "
FAIL = "  [FAIL]"
WARN = "  [WARN]"

failures: list[str] = []


def _fail(msg: str) -> None:
    failures.append(msg)
    print(f"{FAIL} {msg}")


def _ok(msg: str) -> None:
    print(f"{OK} {msg}")


def main() -> int:
    print("=" * 62)
    print("发布链路自检")
    print("=" * 62)

    # ---------- 1. 版本信息 ----------
    print("\n[1] 版本配置")
    try:
        info = build_client_version_out(None)
    except Exception as exc:  # noqa: BLE001
        _fail(f"读取版本信息失败: {exc}")
        return 1
    _ok(f"latest={info.latest}  min_supported={info.min_supported}")

    if not info.download_url:
        _fail("download_url 为空，客户端无法下载")
        return 1

    signed_url = info.download_url
    bare_url = signed_url.split("?", 1)[0]

    # ---------- 2. 签名状态 ----------
    print("\n[2] COS 预签名")
    if cos_presign.is_enabled():
        _ok(f"已启用 | bucket={settings.cos_bucket} region={settings.cos_region}")
    else:
        print(f"{WARN} 未启用（缺少 COS_SECRET_ID/KEY/BUCKET），当前返回的是裸链")

    if "q-signature" in signed_url:
        _ok("download_url 含 q-signature")
    else:
        _fail("download_url 不含 q-signature，签名未生效")
    print(f"        裸链: {bare_url}")

    # ---------- 3. 签名链接可下载 ----------
    print("\n[3] 签名链接下载")
    try:
        with requests.get(signed_url, stream=True, timeout=TIMEOUT) as resp:
            status = resp.status_code
            if status != 200:
                _fail(f"签名链接返回 HTTP {status}（预期 200）")
                body = b""
                try:
                    body = resp.raw.read(300)
                except Exception:  # noqa: BLE001
                    pass
                if body:
                    print(f"        响应: {body.decode('utf-8', 'ignore')[:200]}")
            else:
                head = next(resp.iter_content(chunk_size=2 * 1024 * 1024))
                _ok(f"HTTP 200 | 首块 {len(head) / 1024 / 1024:.1f} MB | 文件头 {head[:2]!r}")
                if head[:2] != b"MZ":
                    _fail("文件头不是 MZ，下载到的可能不是 Windows 可执行文件")
                remote_len = int(resp.headers.get("content-length") or 0)
                installer_name = unquote(urlparse(bare_url).path.rsplit("/", 1)[-1])
                local = Path(settings.client_releases_dir) if settings.client_releases_dir else None
                if local is None:
                    candidate = SERVER_DIR.parent / "release" / installer_name
                    local = candidate if candidate.is_file() else None
                if local and local.is_file():
                    local_size = local.stat().st_size
                    if remote_len == local_size:
                        _ok(f"文件大小一致: {local_size} 字节")
                    else:
                        _fail(f"文件大小不一致: 远端 {remote_len} vs 本地 {local_size}")
                elif remote_len:
                    _ok(f"远端文件大小: {remote_len} 字节（本地无同名安装包，跳过比对）")
    except requests.RequestException as exc:
        _fail(f"签名链接请求异常: {exc}")

    # ---------- 4. 裸链应被拒绝 ----------
    print("\n[4] 裸链防护")
    try:
        resp = requests.head(bare_url, timeout=TIMEOUT, allow_redirects=True)
        if resp.status_code in (401, 403):
            _ok(f"裸链返回 {resp.status_code}，私有桶生效")
        elif resp.status_code == 200:
            _fail("裸链仍可匿名下载！桶权限或对象 ACL 未设为私有")
        else:
            print(f"{WARN} 裸链返回 {resp.status_code}（既非 200 也非 403，请人工确认）")
    except requests.RequestException as exc:
        _fail(f"裸链请求异常: {exc}")

    # ---------- 汇总 ----------
    print("\n" + "=" * 62)
    if failures:
        print(f"结果：{len(failures)} 项失败")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("结果：全部通过，客户端可正常更新下载")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
