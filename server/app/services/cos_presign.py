"""腾讯云 COS 预签名直链。

安装包体积大（数百 MB），放在 COS 上会按外网下行流量计费。
若桶保持「公共读」，任何人拿到裸链就能无限下载、绕开服务端计数，
因此推荐把桶改为「私有读写」，由本模块在每次 /api/client/version 请求时
现场签发一条短时效 GET 直链。

设计要点：
- 纯本地 HMAC 计算，不产生网络请求，单次开销在毫秒级；
- 未配置密钥或未安装 SDK 时返回空串，调用方自动回退到原静态地址，
  保证升级过程中线上行为不中断；
- 客户端无需任何改动：它只是 GET 接口返回的 download_url。
"""

from __future__ import annotations

import logging
from urllib.parse import unquote, urlparse

from app.config import settings

logger = logging.getLogger(__name__)

_client = None
_init_failed = False


def _get_client():
    """惰性初始化 COS 客户端；不可用时只尝试一次，避免反复报错。"""
    global _client, _init_failed
    if _client is not None or _init_failed:
        return _client

    if not (settings.cos_secret_id and settings.cos_secret_key and settings.cos_bucket):
        _init_failed = True
        return None

    try:
        from qcloud_cos import CosConfig, CosS3Client
    except ImportError:
        logger.warning(
            "未安装 cos-python-sdk-v5，安装包直链将回退为静态地址（pip install cos-python-sdk-v5）"
        )
        _init_failed = True
        return None

    try:
        config = CosConfig(
            Region=settings.cos_region,
            SecretId=settings.cos_secret_id,
            SecretKey=settings.cos_secret_key,
            Scheme="https",
        )
        _client = CosS3Client(config)
        logger.info("COS 预签名已启用：bucket=%s region=%s", settings.cos_bucket, settings.cos_region)
    except Exception as exc:  # pragma: no cover - 配置异常兜底
        logger.warning("初始化 COS 客户端失败，回退静态直链：%s", exc)
        _init_failed = True
        return None

    return _client


def is_enabled() -> bool:
    return _get_client() is not None


def reset_cache() -> None:
    """测试用：重置惰性初始化状态。"""
    global _client, _init_failed
    _client = None
    _init_failed = False


def object_key_from_url(url: str) -> str:
    """从 COS 裸链中提取对象键。

    例：https://bucket.cos.ap-guangzhou.myqcloud.com/%E5%89%AA...exe
        -> 剪辑助手-v0.0.21-installer.exe

    若配置了 cos_object_prefix 且路径中没有该前缀，会自动补上，
    这样 version.json 里既可以写完整裸链，也可以只写文件名。
    """
    path = unquote(urlparse((url or "").strip()).path or "").lstrip("/")
    if not path:
        return ""
    prefix = (settings.cos_object_prefix or "").strip().strip("/")
    if prefix and not path.startswith(f"{prefix}/"):
        return f"{prefix}/{path}"
    return path


def presign_get_url(key: str, *, ttl_seconds: int | None = None) -> str:
    """签发 GET 预签名直链；失败返回空串，由调用方回退。"""
    client = _get_client()
    if client is None or not key:
        return ""

    ttl = int(ttl_seconds or settings.cos_signed_url_ttl_seconds or 1800)
    # COS 预签名有效期上限 7200 秒
    ttl = max(60, min(ttl, 7200))
    try:
        return client.get_presigned_url(
            Bucket=settings.cos_bucket,
            Key=key,
            Method="GET",
            Expired=ttl,
        )
    except Exception as exc:
        logger.warning("生成 COS 预签名直链失败（key=%s）：%s", key, exc)
        return ""
