"""登录完成判定与账号标识回填的单元测试。

不依赖真实浏览器：用假的 context/page 模拟 Cookie 逐步出现。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.data.services.changdu_login_service import (  # noqa: E402
    _ensure_account_ids,
    _verify_saved_auth,
    _wait_for_account_cookies,
    _wait_for_login_cookies,
)


class _FakeContext:
    def __init__(self, cookie_steps: list[list[str]], store: list[dict] | None = None):
        self._steps = cookie_steps
        self._calls = 0
        self._store: list[dict] = list(store or [])

    def cookies(self):
        if self._store:
            return self._store
        idx = min(self._calls, len(self._steps) - 1)
        self._calls += 1
        return [{"name": n, "value": "x"} for n in self._steps[idx]]

    def add_cookies(self, cookies):
        self._store.extend(cookies)


class _FakePage:
    def __init__(self, close_after: int | None = None, js_values: dict | None = None):
        self.polls = 0
        self._close_after = close_after
        self._js = js_values or {}
        self.url = "https://www.changdupingtai.com/page/home"

    def wait_for_timeout(self, ms: int) -> None:
        self.polls += 1
        if self._close_after is not None and self.polls >= self._close_after:
            raise _TargetClosedError("Target page, context or browser has been closed")

    def evaluate(self, script, arg=None):
        return self._js.get(arg)


class _TargetClosedError(Exception):
    pass


# ---------- 登录完成判定：以会话 Cookie 为准 ----------


def test_waits_until_session_cookies_appear():
    ctx = _FakeContext([[], ["sessionid"], ["sessionid", "sid_guard"]])
    page = _FakePage()

    _wait_for_login_cookies(ctx, page)

    assert page.polls == 2


def test_returns_immediately_when_session_present():
    ctx = _FakeContext([["sessionid", "sid_guard"]])
    page = _FakePage()

    _wait_for_login_cookies(ctx, page)

    assert page.polls == 0


def test_aduser_id_alone_is_not_login():
    """adUserId 只是账号标识，不能作为登录依据。"""
    ctx = _FakeContext([["adUserId", "rootAdUserId"]])
    page = _FakePage(close_after=3)

    with pytest.raises(RuntimeError, match="浏览器已关闭"):
        _wait_for_login_cookies(ctx, page)


def test_browser_closed_raises_runtime_error():
    ctx = _FakeContext([[]])
    page = _FakePage(close_after=1)

    with pytest.raises(RuntimeError, match="浏览器已关闭"):
        _wait_for_login_cookies(ctx, page)


def test_url_fallback_returns_missing_instead_of_hanging():
    """进入销售页即视为登录动作完成，返回缺失项而不是无限等待。"""
    ctx = _FakeContext([[]])
    page = _FakePage()
    page.url = "https://www.changdupingtai.com/sale/short-play/list"

    missing = _wait_for_login_cookies(ctx, page, settle_s=0.01)

    assert set(missing) == {"sessionid", "sid_guard"}


# ---------- 账号标识回填 ----------


def test_wait_for_account_cookies_returns_immediately_when_present():
    ctx = _FakeContext([], store=[{"name": "adUserId", "value": "1"},
                                  {"name": "rootAdUserId", "value": "2"}])
    page = _FakePage()

    assert _wait_for_account_cookies(ctx, page, timeout_s=5) == []


def test_wait_for_account_cookies_reports_missing_after_timeout():
    ctx = _FakeContext([], store=[{"name": "sessionid", "value": "s"}])
    page = _FakePage()

    missing = _wait_for_account_cookies(ctx, page, timeout_s=0.2, poll_ms=50)

    assert missing == ["adUserId"]


def test_account_ids_already_present():
    ctx = _FakeContext([], store=[{"name": "adUserId", "value": "1"},
                                  {"name": "rootAdUserId", "value": "2"}])
    page = _FakePage()

    assert _ensure_account_ids(ctx, page) == []


def test_account_ids_recovered_from_page_storage():
    ctx = _FakeContext([], store=[{"name": "sessionid", "value": "s"}])
    page = _FakePage(js_values={"adUserId": "111", "rootAdUserId": "222"})

    assert _ensure_account_ids(ctx, page) == []
    names = {c["name"] for c in ctx.cookies()}
    assert {"adUserId", "rootAdUserId"} <= names


def test_account_ids_missing_reported():
    ctx = _FakeContext([], store=[{"name": "sessionid", "value": "s"}])
    page = _FakePage(js_values={})

    assert _ensure_account_ids(ctx, page) == ["adUserId"]


# ---------- 保存后校验 ----------


def test_verify_saved_auth_ok(tmp_path: Path):
    f = tmp_path / "auth.json"
    f.write_text(json.dumps({"cookies": [{"name": "sessionid"}, {"name": "sid_guard"},
                                         {"name": "adUserId"}, {"name": "rootAdUserId"}]}),
                 encoding="utf-8")
    assert _verify_saved_auth(f) == []


def test_verify_saved_auth_missing_session(tmp_path: Path):
    f = tmp_path / "auth.json"
    f.write_text(json.dumps({"cookies": [{"name": "adUserId"}]}), encoding="utf-8")

    with pytest.raises(RuntimeError, match="缺少会话 Cookie"):
        _verify_saved_auth(f)


def test_verify_saved_auth_reports_missing_account_ids(tmp_path: Path):
    f = tmp_path / "auth.json"
    f.write_text(json.dumps({"cookies": [{"name": "sessionid"}, {"name": "sid_guard"}]}),
                 encoding="utf-8")

    assert _verify_saved_auth(f) == ["adUserId"]
