import pytest
from unittest.mock import MagicMock
from app.common.config import cfg, qconfig
from app.data.services.quota_service import DailyQuota
from app.data.api import api as api_module


def test_daily_quota_from_api_enabled_tabs():
    data = {
        "plan_count": 1,
        "clip_count": 2,
        "download_count": 3,
        "download_enabled": True,
        "enabled_tabs": ["batch_edit", "clip_edit"],
    }
    quota = DailyQuota.from_api(data)
    assert quota.enabled_tabs == ["batch_edit", "clip_edit"]

    data_no_tabs = {
        "download_enabled": False,
    }
    quota_no_tabs = DailyQuota.from_api(data_no_tabs)
    assert quota_no_tabs.enabled_tabs == ["clip_edit"]


def test_remote_api_syncs_enabled_tabs(mocker):
    api = api_module.RemoteApi("http://test-server")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b'{"access_token": "abc", "user": {"username": "test", "enabled_tabs": ["batch_edit"]}}'
    mock_resp.json.return_value = {
        "access_token": "abc",
        "user": {"username": "test", "enabled_tabs": ["batch_edit"]},
    }
    mocker.patch.object(api._session, "request", return_value=mock_resp)

    res = api.login("test", "pwd")
    assert res.enabled_tabs == ["batch_edit"]
    assert cfg.enabled_tabs.value == "batch_edit"


def test_can_clip_and_batch_limits():
    from app.data.services.quota_service import QuotaService, DailyQuota

    qs = QuotaService.instance()
    qs._quota = DailyQuota(
        clip_count=10,
        clip_limit=10,
        clipped_dramas=["剧目A"],
    )

    # 单剧目测试：已剪辑过的放行，新剧目超额拦截并返回明确中文提示
    allowed, msg = qs.can_clip("剧目A", refresh=False)
    assert allowed is True

    allowed, msg = qs.can_clip("剧目B", refresh=False)
    assert allowed is False
    assert msg == "今日剪辑剧目数已达上限（10 部）"

    # 批量测试：剩余 0 部
    allowed, msg, rem = qs.can_clip_batch(["剧目A", "剧目B", "剧目C"], refresh=False)
    assert allowed is False
    assert rem == 0
    assert "今日剪辑剧目数已达上限（10 部）" in msg

    # 批量测试：部分剩余
    qs._quota = DailyQuota(
        clip_count=8,
        clip_limit=10,
        clipped_dramas=["剧目A"],
    )
    allowed, msg, rem = qs.can_clip_batch(["剧目A", "剧目B", "剧目C", "剧目D"], refresh=False)
    assert allowed is False
    assert rem == 2
    assert "今日剩余剪辑额度为 2 部" in msg


def test_check_remote_quota_and_security_masking(mocker):
    from app.data.services.quota_service import QuotaService
    from app.data.services.access_control_service import _RANDOM_ERRORS
    from app.data.api.api import ApiError

    qs = QuotaService.instance()
    mock_api = MagicMock()

    # 1. 正常业务配额满额（HTTP 200, allowed=False）
    mock_api.check_daily_quota.return_value = {
        "allowed": False,
        "message": "今日剪辑剧目数已达上限（15 部）",
        "quota": {"clip_count": 15, "clip_limit": 15},
    }
    mocker.patch("app.data.services.quota_service.get_api", return_value=mock_api)
    allowed, msg = qs.check_remote("clip", "剧目X")
    assert allowed is False
    assert msg == "今日剪辑剧目数已达上限（15 部）"

    # 2. 安全防探知（HTTP 403 / 账号封禁 / 到期）：必须坚决返回随机混淆报错，绝不泄露真实原因
    mock_api.check_daily_quota.side_effect = ApiError("无效", status_code=403)
    allowed, msg = qs.check_remote("clip", "剧目X")
    assert allowed is False
    assert msg in _RANDOM_ERRORS

