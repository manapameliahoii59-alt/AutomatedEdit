"""一键发布安装包：上传 COS → 校验远端 → 写 version.json → 线上自检。

凭据读取顺序：环境变量 COS_SECRET_ID / COS_SECRET_KEY / COS_BUCKET / COS_REGION
→ 本地文件 ~/.automatededit/release.env。仓库内不保存任何密钥。

用法（仓库根目录）：
    uv run python scripts/publish_release.py                     # 完整发布
    uv run python scripts/publish_release.py --dry-run           # 只检查，不上传
    uv run python scripts/publish_release.py --skip-verify       # 跳过线上自检
    uv run python scripts/publish_release.py --changelog-file notes.txt
    uv run python scripts/publish_release.py --force             # 覆盖已存在的同版本对象
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from _app_meta import APP_NAME, VERSION  # noqa: E402
from write_release_version import write_release_version  # noqa: E402

ENV_FILE = Path.home() / ".automatededit" / "release.env"
DEFAULT_API_BASE = "http://129.204.86.63:7172"
REQUIRED_ENV = ("COS_SECRET_ID", "COS_SECRET_KEY", "COS_BUCKET", "COS_REGION")

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass


def load_credentials() -> dict[str, str]:
    """环境变量优先，其次读本地凭据文件。"""
    env = {k: os.environ.get(k, "").strip() for k in REQUIRED_ENV}
    if all(env.values()):
        return env
    if ENV_FILE.is_file():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k in REQUIRED_ENV and not env.get(k):
                env[k] = v
    missing = [k for k in REQUIRED_ENV if not env.get(k)]
    if missing:
        raise SystemExit(
            f"缺少 COS 凭据：{', '.join(missing)}\n"
            f"请设置环境变量，或写入 {ENV_FILE}"
        )
    return env


def cos_url(bucket: str, region: str, filename: str) -> str:
    return f"https://{bucket}.cos.{region}.myqcloud.com/{quote(filename)}"


def human(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB"


def main() -> int:
    parser = argparse.ArgumentParser(description="上传安装包到 COS 并发布版本")
    parser.add_argument("--version", default=VERSION, help=f"发布版本号（默认 {VERSION}）")
    parser.add_argument("--file", default="", help="安装包路径（默认 release/<名称>-v<版本>-installer.exe）")
    parser.add_argument("--min-supported", default=None, help="最低支持版本（默认沿用 version.json 现值）")
    parser.add_argument("--changelog", default="", help="更新说明")
    parser.add_argument("--changelog-file", default="", help="从文件读取更新说明")
    parser.add_argument("--skip-upload", action="store_true", help="跳过上传，只写 version.json")
    parser.add_argument("--skip-verify", action="store_true", help="跳过线上自检")
    parser.add_argument("--dry-run", action="store_true", help="只做本地检查，不产生任何改动")
    parser.add_argument("--force", action="store_true", help="允许覆盖 COS 上已存在的同名对象")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help=f"线上接口地址（默认 {DEFAULT_API_BASE}）")
    args = parser.parse_args()

    version = args.version.strip()
    filename = f"{APP_NAME}-v{version}-installer.exe"
    local_file = Path(args.file) if args.file else (ROOT / "release" / filename)

    print("=" * 62)
    print(f"发布 {APP_NAME} v{version}")
    print("=" * 62)

    # ---------- 1. 本地安装包 ----------
    print("\n[1] 本地安装包")
    if not local_file.is_file():
        print(f"  [FAIL] 找不到安装包：{local_file}")
        print("         请先执行打包（scripts/build.py 或 iscc scripts/pack_installer.iss）")
        return 1
    local_size = local_file.stat().st_size
    if local_file.name != filename:
        print(f"  [WARN] 文件名与版本不匹配，将按 {filename} 上传")
    print(f"  [OK]   {local_file.name}  {human(local_size)}（{local_size} 字节）")
    if local_size < 10 * 1024 * 1024:
        print("  [WARN] 文件小于 10MB，可能不是完整安装包")

    env = load_credentials()
    bucket, region = env["COS_BUCKET"], env["COS_REGION"]
    target_url = cos_url(bucket, region, filename)

    if args.dry_run:
        print("\n[dry-run] 将上传到：")
        print(f"  bucket={bucket} region={region}")
        print(f"  key={filename}")
        print(f"  url={target_url}")
        return 0

    try:
        from qcloud_cos import CosConfig, CosS3Client
        from qcloud_cos.cos_exception import CosServiceError
    except ImportError:
        print("  [FAIL] 未安装 cos-python-sdk-v5，请用：")
        print("         uv run --with cos-python-sdk-v5 python scripts/publish_release.py")
        return 1

    client = CosS3Client(
        CosConfig(
            Region=region,
            SecretId=env["COS_SECRET_ID"],
            SecretKey=env["COS_SECRET_KEY"],
            Scheme="https",
        )
    )

    # ---------- 2. 上传 ----------
    print("\n[2] 上传到 COS")
    if not args.skip_upload:
        exists = False
        try:
            client.head_object(Bucket=bucket, Key=filename)
            exists = True
        except CosServiceError:
            exists = False

        if exists and not args.force:
            print(f"  [FAIL] COS 上已存在 {filename}")
            print("         版本号未变更？确认要覆盖请加 --force（覆盖会破坏正在下载该版本的用户）")
            return 1
        if exists:
            print("  [WARN] 覆盖已存在的同名对象（--force）")

        last_shown = {"pct": -1}

        def _progress(done: int, total: int) -> None:
            pct = int(done * 100 / total) if total else 0
            if pct >= last_shown["pct"] + 5 or pct == 100:
                last_shown["pct"] = pct
                print(f"         上传中 {pct}%  ({human(done)} / {human(total)})", flush=True)

        try:
            client.upload_file(
                Bucket=bucket,
                Key=filename,
                LocalFilePath=str(local_file),
                PartSize=20,
                MAXThread=5,
                progress_callback=_progress,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  [FAIL] 上传失败：{type(exc).__name__}: {exc}")
            print("         若是 403，检查子账号是否有 PutObject 与 *MultipartUpload 权限")
            return 1
        print("  [OK]   上传完成")
    else:
        print("  [SKIP] --skip-upload")

    # ---------- 3. 远端校验 ----------
    print("\n[3] 远端校验")
    try:
        head = client.head_object(Bucket=bucket, Key=filename)
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] 读取远端对象失败：{exc}")
        return 1
    remote_size = int(head.get("Content-Length") or 0)
    if remote_size == local_size:
        print(f"  [OK]   大小一致：{remote_size} 字节")
    else:
        print(f"  [FAIL] 大小不一致：远端 {remote_size} vs 本地 {local_size}")
        return 1
    print(f"  [OK]   ETag: {head.get('ETag')}")

    # ---------- 4. 写 version.json ----------
    print("\n[4] 写入 release/version.json")
    changelog = args.changelog
    if args.changelog_file:
        changelog = Path(args.changelog_file).read_text(encoding="utf-8").strip()
    if not changelog:
        # 未提供更新说明时沿用上一版内容，避免被通用默认文案覆盖
        existing = ROOT / "release" / "version.json"
        if existing.is_file():
            try:
                changelog = str(json.loads(existing.read_text(encoding="utf-8")).get("changelog") or "")
            except Exception:  # noqa: BLE001
                changelog = ""
        if changelog:
            print("  [WARN] 未提供 --changelog，沿用上一版更新说明")
        else:
            print("  [WARN] 未提供 --changelog，将写入通用默认文案")
    path = write_release_version(
        changelog=changelog,
        min_supported=args.min_supported,
        download_url=target_url,
    )
    data = path.read_text(encoding="utf-8")
    print(f"  [OK]   {path}")
    for line in data.strip().splitlines():
        print(f"         {line}")

    # ---------- 5. 线上自检 ----------
    if args.skip_verify:
        print("\n[5] 线上自检  [SKIP]")
        return 0

    print("\n[5] 线上自检")
    print("  [注意] 需先把 version.json 同步到服务器才会生效，当前校验的是服务器上的旧配置")
    try:
        import requests
    except ImportError:
        print("  [SKIP] 未安装 requests")
        return 0

    api = args.api_base.rstrip("/")
    try:
        resp = requests.get(f"{api}/api/client/version", timeout=20)
        info = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] 接口不可用：{exc}")
        return 1

    if str(info.get("latest")) != version:
        print(f"  [WARN] 线上 latest={info.get('latest')}，与你发布的 {version} 不一致")
        print("         这是预期内的：version.json 还没同步到服务器")

    url = info.get("download_url") or ""
    if "q-signature" not in url:
        print("  [FAIL] 线上 download_url 不含签名，服务端 COS 未启用")
        return 1
    print("  [OK]   线上返回签名链接")

    key = unquote(urlparse(url).path.lstrip("/"))
    if key != filename:
        print(f"  [WARN] 线上指向的对象是 {key}，不是 {filename}")

    try:
        with requests.get(url, stream=True, timeout=(15, 60)) as r:
            if r.status_code != 200:
                print(f"  [FAIL] 签名链接返回 {r.status_code}")
                return 1
            head_bytes = next(r.iter_content(chunk_size=1024 * 1024))
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] 下载校验失败：{exc}")
        return 1
    if head_bytes[:2] != b"MZ":
        print("  [FAIL] 文件头不是 MZ")
        return 1
    print(f"  [OK]   签名链接可下载，文件头 MZ")

    print("\n" + "=" * 62)
    print("发布完成。下一步：把 release/version.json 同步到服务器后重启/刷新配置")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
