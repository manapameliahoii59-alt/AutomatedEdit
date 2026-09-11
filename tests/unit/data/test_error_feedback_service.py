import pytest

from app.common.error_sanitizer import (
    sanitize_plan_error,
    sanitize_render_error,
    sanitize_transcribe_error,
)
from app.data.services.error_feedback_service import (
    ErrorFeedbackService,
    ErrorReportData,
    error_feedback_service,
)


class TestErrorFeedbackService:
    def test_record_error_with_exception(self):
        svc = ErrorFeedbackService()
        try:
            raise ValueError("测试音频损坏")
        except Exception as exc:
            rep = svc.record_error(
                stage="transcribe",
                drama_name="逆子归来",
                friendly_msg="音频识别遇到异常，请检查视频文件后重试",
                raw_error=exc,
            )

        assert rep.error_stage == "transcribe"
        assert rep.drama_name == "逆子归来"
        assert rep.friendly_msg == "音频识别遇到异常，请检查视频文件后重试"
        assert "ValueError: 测试音频损坏" in rep.raw_error
        assert rep.app_version != ""
        assert "OS:" in rep.client_info
        assert rep.submitted is False
        assert svc.get_latest_report() is rep

    def test_find_matching_report(self):
        svc = ErrorFeedbackService()
        rep = svc.record_error(
            stage="render",
            drama_name="剧目A",
            friendly_msg="视频渲染合成失败，请检查文件后重试",
            raw_error="FFmpeg exit code 1",
        )

        # 匹配 friendly_msg
        found = svc.find_matching_report("《剧目A》视频渲染合成失败，请检查文件后重试")
        assert found is rep

        # 匹配 drama_name
        found2 = svc.find_matching_report("《剧目A》出错了")
        assert found2 is rep

        # 兜底匹配错误关键词
        found3 = svc.find_matching_report("操作失败")
        assert found3 is rep

        # 已提交的不再重复匹配
        rep.submitted = True
        assert svc.find_matching_report("操作失败") is None

    def test_submit_report_success(self, mocker):
        svc = ErrorFeedbackService()
        rep = svc.record_error(
            stage="plan",
            drama_name="测试短剧",
            friendly_msg="智能策划方案生成失败",
            raw_error="LLM timeout",
        )

        mock_api = mocker.MagicMock()
        mock_api.post_error_report.return_value = {"ok": True, "id": 123}
        mocker.patch("app.data.services.error_feedback_service.get_api", return_value=mock_api)

        ok, msg = svc.submit_report(rep)
        assert ok is True
        assert msg == ""
        assert rep.submitted is True
        mock_api.post_error_report.assert_called_once()
        args = mock_api.post_error_report.call_args[0][0]
        assert args["error_stage"] == "plan"
        assert args["drama_name"] == "测试短剧"
        assert args["raw_error"] == "LLM timeout"

    def test_submit_report_failure(self, mocker):
        svc = ErrorFeedbackService()
        rep = svc.record_error(
            stage="plan",
            drama_name="测试短剧",
            friendly_msg="智能策划方案生成失败",
            raw_error="LLM timeout",
        )

        mock_api = mocker.MagicMock()
        mock_api.post_error_report.side_effect = Exception("网络不可达")
        mocker.patch("app.data.services.error_feedback_service.get_api", return_value=mock_api)

        ok, msg = svc.submit_report(rep)
        assert ok is False
        assert "网络不可达" in msg
        assert rep.submitted is False

    def test_submit_matching_report_success_and_dedupe(self, mocker):
        svc = ErrorFeedbackService()
        mock_api = mocker.MagicMock()
        mock_api.post_error_report.return_value = {"ok": True, "id": 1}
        mocker.patch("app.data.services.error_feedback_service.get_api", return_value=mock_api)

        rep = svc.record_error(
            stage="render",
            drama_name="剧目B",
            friendly_msg="视频渲染合成失败，请检查文件后重试",
            raw_error="ffmpeg exit 1",
        )
        assert svc.submit_matching_report("《剧目B》视频渲染合成失败，请检查文件后重试") is True
        assert rep.submitted is True
        assert mock_api.post_error_report.call_count == 1

        # 同内容 60 秒内再次出现，不再重复上报
        svc.record_error(
            stage="render",
            drama_name="剧目B",
            friendly_msg="视频渲染合成失败，请检查文件后重试",
            raw_error="ffmpeg exit 1 again",
        )
        assert svc.submit_matching_report("《剧目B》视频渲染合成失败，请检查文件后重试") is False
        assert mock_api.post_error_report.call_count == 1

    def test_submit_matching_report_returns_false_without_match(self, mocker):
        svc = ErrorFeedbackService()
        mock_api = mocker.MagicMock()
        mocker.patch("app.data.services.error_feedback_service.get_api", return_value=mock_api)

        assert svc.submit_matching_report("这里没有任何匹配的异常") is False
        mock_api.post_error_report.assert_not_called()

    def test_submit_matching_report_failure_retries(self, mocker):
        svc = ErrorFeedbackService()
        mock_api = mocker.MagicMock()
        mock_api.post_error_report.side_effect = Exception("网络不可达")
        mocker.patch("app.data.services.error_feedback_service.get_api", return_value=mock_api)

        svc.record_error(
            stage="plan",
            drama_name="剧目C",
            friendly_msg="智能策划方案生成失败，请稍后重试",
            raw_error="timeout",
        )
        assert svc.submit_matching_report("《剧目C》智能策划方案生成失败，请稍后重试") is False
        # 失败不写入去重窗口，可再次尝试
        assert svc.submit_matching_report("《剧目C》智能策划方案生成失败，请稍后重试") is False
        assert mock_api.post_error_report.call_count == 2


class TestErrorSanitizerIntegration:
    def test_transcribe_error_records_feedback(self):
        try:
            raise RuntimeError("Torch not found / DLL load failure")
        except Exception as e:
            res = sanitize_transcribe_error(e, drama_name="逆子归来")

        assert "逆子归来" in res
        latest = error_feedback_service.get_latest_report()
        assert latest is not None
        assert latest.error_stage == "transcribe"
        assert latest.drama_name == "逆子归来"
        assert "Torch not found" in latest.raw_error

    def test_plan_error_records_feedback(self):
        res = sanitize_plan_error("504 Gateway Timeout from AI server", drama_name="豪门狂婿")
        assert "豪门狂婿" in res
        latest = error_feedback_service.get_latest_report()
        assert latest is not None
        assert latest.error_stage == "plan"
        assert latest.drama_name == "豪门狂婿"
        assert "504 Gateway Timeout" in latest.raw_error

    def test_cancellation_does_not_record_feedback(self):
        # 记录前一个
        prev = error_feedback_service.get_latest_report()
        res = sanitize_render_error("用户已取消操作", drama_name="测试取消")
        assert "渲染已取消" in res
        # 最新的 report 依然是之前的那个，而不是“用户已取消”
        latest = error_feedback_service.get_latest_report()
        assert latest == prev or (latest and latest.drama_name != "测试取消")
