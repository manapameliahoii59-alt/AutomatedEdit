import json
import sys
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.config import settings
from app.services import client_version as client_version_service
from app.services import cos_presign

COS_URL = (
    "https://dragoncos-1394428777.cos.ap-guangzhou.myqcloud.com/"
    "%E5%89%AA%E8%BE%91%E5%8A%A9%E6%89%8B-v0.0.21-installer.exe"
)


@pytest.fixture(autouse=True)
def _reset_cos_cache():
    cos_presign.reset_cache()
    yield
    cos_presign.reset_cache()


def _enable_fake_cos(monkeypatch, *, prefix: str = "") -> None:
    monkeypatch.setattr(settings, "cos_secret_id", "AKIDFAKEtestkey123456")
    monkeypatch.setattr(settings, "cos_secret_key", "fakesecretkey1234567890")
    monkeypatch.setattr(settings, "cos_bucket", "dragoncos-1394428777")
    monkeypatch.setattr(settings, "cos_region", "ap-guangzhou")
    monkeypatch.setattr(settings, "cos_object_prefix", prefix)
    monkeypatch.setattr(settings, "cos_signed_url_ttl_seconds", 1800)
    cos_presign.reset_cache()


def test_object_key_from_url():
    assert cos_presign.object_key_from_url(COS_URL) == "剪辑助手-v0.0.21-installer.exe"
    assert cos_presign.object_key_from_url("app-v2.exe") == "app-v2.exe"
    assert cos_presign.object_key_from_url("") == ""


def test_object_key_applies_configured_prefix(monkeypatch):
    _enable_fake_cos(monkeypatch, prefix="release")
    # version.json 只写文件名时，按配置补前缀
    assert cos_presign.object_key_from_url("app-v2.exe") == "release/app-v2.exe"
    # 已带前缀的完整裸链保持原样
    assert (
        cos_presign.object_key_from_url(
            "https://x.cos.ap-guangzhou.myqcloud.com/release/app-v2.exe"
        )
        == "release/app-v2.exe"
    )


def test_disabled_without_credentials(monkeypatch):
    monkeypatch.setattr(settings, "cos_secret_id", "")
    monkeypatch.setattr(settings, "cos_secret_key", "")
    monkeypatch.setattr(settings, "cos_bucket", "")
    cos_presign.reset_cache()

    assert cos_presign.is_enabled() is False
    assert cos_presign.presign_get_url("app-v2.exe") == ""


def test_download_url_falls_back_to_bare_link(monkeypatch, tmp_path):
    """未配置 COS 时保持原有静态直链，线上行为不变。"""
    monkeypatch.setattr(settings, "cos_secret_id", "")
    monkeypatch.setattr(settings, "cos_secret_key", "")
    monkeypatch.setattr(settings, "cos_bucket", "")
    cos_presign.reset_cache()
    monkeypatch.setattr(settings, "client_releases_dir", str(tmp_path))
    (tmp_path / "version.json").write_text(
        json.dumps(
            {"latest": "0.0.21", "min_supported": "0.0.20", "download_url": COS_URL},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    out = client_version_service.build_client_version_out()
    assert out.download_url == COS_URL
    assert "q-signature" not in out.download_url


def test_download_url_uses_presigned_link(monkeypatch, tmp_path):
    """配置 COS 后返回短时效签名直链，裸链不再对外暴露。"""
    _enable_fake_cos(monkeypatch)
    monkeypatch.setattr(settings, "client_releases_dir", str(tmp_path))
    (tmp_path / "version.json").write_text(
        json.dumps(
            {"latest": "0.0.21", "min_supported": "0.0.20", "download_url": COS_URL},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    out = client_version_service.build_client_version_out()
    assert "q-signature" in out.download_url
    assert "q-sign-time" in out.download_url
    assert out.download_url.startswith(
        "https://dragoncos-1394428777.cos.ap-guangzhou.myqcloud.com/"
    )
    # 签名链接仍需保留原始（URL 编码后的）对象路径
    assert "%E5%89%AA%E8%BE%91%E5%8A%A9%E6%89%8B" in out.download_url
