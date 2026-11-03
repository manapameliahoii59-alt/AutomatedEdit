"""浏览器上下文参数与临时产物清理的单元测试。

背景：Playwright 默认 accept_downloads=True，页面一旦触发下载，文件会静默
落到 %TEMP%\\playwright-artifacts-*\\ 且永不清理（实测累积过 32GB）。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.data.services import changdu_browser  # noqa: E402


def test_context_disables_download_capture():
    """必须显式关闭下载捕获，否则浏览器下载会堆进系统临时目录。"""
    kwargs = changdu_browser.browser_context_kwargs()
    assert kwargs["accept_downloads"] is False


def test_context_keeps_stealth_fields():
    """关闭下载捕获不应影响原有的指纹字段。"""
    kwargs = changdu_browser.browser_context_kwargs()
    assert kwargs["user_agent"] == changdu_browser.CHROME_USER_AGENT
    assert kwargs["locale"] == changdu_browser.BROWSER_LOCALE
    assert "viewport" in kwargs and "extra_http_headers" in kwargs


def test_cleanup_removes_only_stale_artifacts(tmp_path, monkeypatch):
    """只删超期目录，正在使用的（新）目录必须保留。"""
    monkeypatch.setattr(changdu_browser.tempfile, "gettempdir", lambda: str(tmp_path))

    old_dir = tmp_path / "playwright-artifacts-OLD"
    new_dir = tmp_path / "playwright-artifacts-NEW"
    other_dir = tmp_path / "unrelated-folder"
    for d in (old_dir, new_dir, other_dir):
        d.mkdir()
        (d / "a.mp4").write_bytes(b"x" * 128)

    stale = time.time() - 30 * 86400
    for d in (old_dir, other_dir):
        os.utime(d, (stale, stale))

    removed = changdu_browser.cleanup_stale_artifacts(max_age_days=7)

    assert removed == 1
    assert not old_dir.exists(), "超期的 artifacts 目录应被删除"
    assert new_dir.exists(), "新建的 artifacts 目录必须保留"
    assert other_dir.exists(), "非 artifacts 目录不得触碰"


def test_cleanup_returns_zero_when_nothing_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(changdu_browser.tempfile, "gettempdir", lambda: str(tmp_path))
    fresh = tmp_path / "playwright-artifacts-FRESH"
    fresh.mkdir()

    assert changdu_browser.cleanup_stale_artifacts(max_age_days=7) == 0
    assert fresh.exists()
