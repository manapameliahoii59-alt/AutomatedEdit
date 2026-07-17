"""RemotePlanService 瞬时网络错误重试。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.data.api.api import ApiError
from app.data.services.remote_plan_service import (
    RemotePlanService,
    _is_transient_api_error,
)


def test_is_transient_api_error_detects_connect_timeout():
    err = ApiError("无法连接服务器（连接超时）：http://x，请检查网络或稍后重试")
    assert _is_transient_api_error(err)
    assert not _is_transient_api_error(ApiError("策划密钥无效", status_code=400))
    assert not _is_transient_api_error(RuntimeError("other"))


def test_call_with_retry_succeeds_after_transient_failures():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise ApiError("无法连接服务器：ConnectTimeout")
        return {"ok": True}

    with patch.object(RemotePlanService, "REQUEST_RETRY_DELAY_SEC", 0):
        assert RemotePlanService._call_with_retry(flaky) == {"ok": True}
    assert calls["n"] == 3


def test_call_with_retry_gives_up_after_retries():
    def always_fail():
        raise ApiError("无法连接服务器：timed out")

    with patch.object(RemotePlanService, "REQUEST_RETRIES", 2):
        with patch.object(RemotePlanService, "REQUEST_RETRY_DELAY_SEC", 0):
            with pytest.raises(ApiError, match="无法连接服务器"):
                RemotePlanService._call_with_retry(always_fail)


def test_call_with_retry_does_not_retry_business_errors():
    calls = {"n": 0}

    def business_fail():
        calls["n"] += 1
        raise ApiError("未登录", status_code=401)

    with pytest.raises(ApiError, match="未登录"):
        RemotePlanService._call_with_retry(business_fail)
    assert calls["n"] == 1
