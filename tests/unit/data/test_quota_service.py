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
