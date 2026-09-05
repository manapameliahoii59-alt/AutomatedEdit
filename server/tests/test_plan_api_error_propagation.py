import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


def _steps():
    return [
        {"source_file": "1.mp4", "start": 2.0, "end": 6.0, "text": "你好呀朋友们今天天气不错"},
        {"source_file": "1.mp4", "start": 10.0, "end": 20.0, "text": "剧情继续发展到这里"},
        {"source_file": "1.mp4", "start": 60.0, "end": 120.0, "text": "第三句台词出现在这里"},
        {"source_file": "2.mp4", "start": 5.0, "end": 15.0, "text": "第二集开场台词"},
        {"source_file": "2.mp4", "start": 20.0, "end": 60.0, "text": "第二集中间台词"},
        {"source_file": "2.mp4", "start": 100.0, "end": 160.0, "text": "第二集结尾台词收尾"},
    ]


_VALID_RESPONSE = (
    '{"starts":[{"se":"1.mp4","st":7.0}],'
    '"ends":[{"le":"2.mp4","ct":"第二集结尾台词收尾","hook":"点进来看大结局"}]}'
)


def test_fatal_api_error_single_key_fails_fast():
    """402/401 等致命错误：单 key 首次调用即终止，并上报真实原因。"""
    from app.services.plan_director import run_plan

    calls: list[str] = []

    def _fake_call(**kwargs):
        calls.append(kwargs["group_type"])
        return None, 0.1, 'HTTP 402: {"error":{"message":"Insufficient Balance"}}'

    with patch("app.services.plan_director._call_deepseek", side_effect=_fake_call):
        with pytest.raises(RuntimeError) as exc_info:
            run_plan(
                project_name="测试",
                steps=_steps(),
                ordered_files=["1.mp4", "2.mp4"],
                api_keys_raw="sk-test",
                api_url="http://example.test",
                model_name="test",
                target_clips_count=5,
                min_duration_seconds=120,
                max_duration_seconds=300,
                split_ab=False,
            )

    msg = str(exc_info.value)
    assert len(calls) == 1  # 首次 fatal 即终止，不再空转 MAX_GROUP_LOOPS 轮
    assert "未产出有效方案" in msg
    assert "HTTP 402" in msg
    assert "余额不足" in msg


def test_fatal_api_error_aborts_after_full_key_pool_round():
    """多 key 全部致命失败：跑完一轮 key 池后立即终止。"""
    from app.services.plan_director import run_plan

    calls: list[str] = []

    def _fake_call(**kwargs):
        calls.append(kwargs["group_type"])
        return None, 0.1, "HTTP 402: Insufficient Balance"

    with patch("app.services.plan_director._call_deepseek", side_effect=_fake_call):
        with pytest.raises(RuntimeError) as exc_info:
            run_plan(
                project_name="测试",
                steps=_steps(),
                ordered_files=["1.mp4", "2.mp4"],
                api_keys_raw="sk-a,sk-b",
                api_url="http://example.test",
                model_name="test",
                target_clips_count=5,
                min_duration_seconds=120,
                max_duration_seconds=300,
                split_ab=False,
            )

    assert len(calls) == 2  # 两个 key 各试一次
    assert "HTTP 402" in str(exc_info.value)


def test_fatal_error_on_one_key_does_not_abort_pool():
    """key 池中仅部分 key 失效：其余 key 仍可继续产出方案。"""
    from app.services.plan_director import run_plan

    calls: list[str] = []

    def _fake_call(**kwargs):
        calls.append(kwargs["group_type"])
        if len(calls) == 1:
            return None, 0.1, "HTTP 402: Insufficient Balance"
        return _VALID_RESPONSE, 0.1, None

    with patch("app.services.plan_director._call_deepseek", side_effect=_fake_call):
        plans = run_plan(
            project_name="测试",
            steps=_steps(),
            ordered_files=["1.mp4", "2.mp4"],
            api_keys_raw="sk-a,sk-b",
            api_url="http://example.test",
            model_name="test",
            target_clips_count=5,
            min_duration_seconds=120,
            max_duration_seconds=300,
            split_ab=False,
        )

    assert len(calls) >= 2
    assert len(plans) >= 1


def test_parse_error_surfaces_in_final_message():
    """模型返回无法解析的内容：最终错误携带最后解析异常。"""
    from app.services.plan_director import run_plan

    with patch(
        "app.services.plan_director._call_deepseek",
        side_effect=lambda **kw: ("抱歉，我无法完成该任务", 0.1, None),
    ):
        with pytest.raises(RuntimeError) as exc_info:
            run_plan(
                project_name="测试",
                steps=_steps(),
                ordered_files=["1.mp4", "2.mp4"],
                api_keys_raw="sk-test",
                api_url="http://example.test",
                model_name="test",
                target_clips_count=5,
                min_duration_seconds=120,
                max_duration_seconds=300,
                split_ab=False,
            )

    msg = str(exc_info.value)
    assert "未产出有效方案" in msg
    assert "最后错误" in msg
    assert "JSONDecodeError" in msg


def test_non_fatal_api_error_surfaces_in_final_message():
    """非致命错误（如 503）：循环重试后失败信息透传到最终异常。"""
    from app.services.plan_director import run_plan

    with patch(
        "app.services.plan_director._call_deepseek",
        side_effect=lambda **kw: (None, 0.1, "HTTP 503: Service Unavailable"),
    ):
        with pytest.raises(RuntimeError) as exc_info:
            run_plan(
                project_name="测试",
                steps=_steps(),
                ordered_files=["1.mp4", "2.mp4"],
                api_keys_raw="sk-test",
                api_url="http://example.test",
                model_name="test",
                target_clips_count=5,
                min_duration_seconds=120,
                max_duration_seconds=300,
                split_ab=False,
            )

    msg = str(exc_info.value)
    assert "未产出有效方案" in msg
    assert "最后错误：HTTP 503" in msg


def test_user_facing_plan_error_hides_technical_cause():
    """客户端可见错误：技术原因（HTTP/密钥/额度）被隐藏，仅保留通用文案。"""
    from app.services.plan_jobs import user_facing_plan_error

    # 402 余额不足 → 通用文案，不含 402/余额/API Key 字样
    masked = user_facing_plan_error(
        "《剧名》策划未产出有效方案：HTTP 402: Insufficient Balance"
        "（模型账户余额不足，请充值或更换 API Key）"
    )
    assert masked == "本次策划未产出有效方案，请稍后重试"
    assert "402" not in masked and "余额" not in masked and "Key" not in masked

    # 解析类错误同样隐藏
    masked2 = user_facing_plan_error(
        "《剧名》策划未产出有效方案（最后错误：JSONDecodeError: ...）"
    )
    assert "JSONDecodeError" not in masked2

    # 服务重启类已是用户友好文案：原样保留
    assert user_facing_plan_error("服务重启，策划任务已中断，请重新策划") == (
        "服务重启，策划任务已中断，请重新策划"
    )

    # 空错误 / 未知技术异常 → 通用兜底
    assert user_facing_plan_error("") == "策划失败，请稍后重试"
    assert user_facing_plan_error("Traceback (most recent call last): ...") == (
        "策划失败，请稍后重试"
    )


def test_plan_job_status_returns_sanitized_error_and_raw_detail():
    """状态接口：error 为脱敏文案，error_detail 携带完整技术原因供开发诊断。"""
    from app.routers.client import get_plan_job_status

    raw_error = (
        "《X》策划未产出有效方案：HTTP 402: Insufficient Balance"
        "（模型账户余额不足，请充值或更换 API Key）"
    )

    class _Row:
        id = "job1"
        user_id = 1
        status = "failed"
        progress_json = "{}"
        error = raw_error
        result_json = ""
        created_at = None
        updated_at = None

    class _Db:
        def scalar(self, _stmt):
            return _Row()

    class _User:
        id = 1

    out = get_plan_job_status("job1", _User(), _Db())
    assert out.error == "本次策划未产出有效方案，请稍后重试"
    assert "HTTP 402" not in out.error
    assert out.error_detail == raw_error
