"""RemotePlanService 任务失败信息组装（开发诊断透传）。"""

from unittest.mock import patch

from app.data.services.remote_plan_service import _job_error_message

_STATUS = {
    "error": "本次策划未产出有效方案，请稍后重试",
    "error_detail": "《X》策划未产出有效方案：HTTP 402: Insufficient Balance（余额不足）",
}


def test_job_error_message_dev_mode_includes_detail():
    with patch(
        "app.data.services.remote_plan_service.is_dev_runtime", return_value=True
    ):
        msg = _job_error_message(_STATUS)
    assert "请稍后重试" in msg
    assert "[开发诊断]" in msg
    assert "HTTP 402" in msg


def test_job_error_message_packaged_mode_hides_detail():
    with patch(
        "app.data.services.remote_plan_service.is_dev_runtime", return_value=False
    ):
        msg = _job_error_message(_STATUS)
    assert msg == "本次策划未产出有效方案，请稍后重试"
    assert "HTTP 402" not in msg
    assert "[开发诊断]" not in msg


def test_job_error_message_empty_error_fallback():
    with patch(
        "app.data.services.remote_plan_service.is_dev_runtime", return_value=False
    ):
        msg = _job_error_message({})
    assert "服务端未返回原因" in msg
