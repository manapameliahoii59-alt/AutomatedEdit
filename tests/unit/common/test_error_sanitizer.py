"""Unit tests for error message sanitization and environment awareness."""

import os
import pytest

from app.common.error_sanitizer import (
    _RE_SENSITIVE_ASR,
    _RE_SENSITIVE_LLM,
    _RE_SENSITIVE_RENDER,
    sanitize_plan_error,
    sanitize_render_error,
    sanitize_transcribe_error,
    sanitize_transcribe_warning,
)


@pytest.fixture(autouse=True)
def clean_env():
    """Ensure environment flags are clean before and after each test."""
    old_dev = os.environ.get("AE_FORCE_DEV_ERROR")
    old_prod = os.environ.get("AE_FORCE_PROD_ERROR")
    yield
    if old_dev is not None:
        os.environ["AE_FORCE_DEV_ERROR"] = old_dev
    else:
        os.environ.pop("AE_FORCE_DEV_ERROR", None)
    if old_prod is not None:
        os.environ["AE_FORCE_PROD_ERROR"] = old_prod
    else:
        os.environ.pop("AE_FORCE_PROD_ERROR", None)


class TestErrorSanitizerDevMode:
    """In development mode, developers must see [开发诊断] with full technical details."""

    def test_transcribe_error_dev_preserves_raw_details(self, monkeypatch):
        monkeypatch.setenv("AE_FORCE_DEV_ERROR", "1")
        monkeypatch.delenv("AE_FORCE_PROD_ERROR", raising=False)

        raw = "SenseVoiceSmall failed to load: torch.cuda.OutOfMemoryError in funasr pipeline"
        result = sanitize_transcribe_error(raw, drama_name="测试剧目")

        assert "[开发诊断]" in result
        assert "SenseVoiceSmall" in result
        assert "torch.cuda.OutOfMemoryError" in result
        assert "《测试剧目》" in result

    def test_plan_error_dev_preserves_raw_details(self, monkeypatch):
        monkeypatch.setenv("AE_FORCE_DEV_ERROR", "1")
        monkeypatch.delenv("AE_FORCE_PROD_ERROR", raising=False)

        raw = "DeepSeek API error: prompt tokens exceeded 32000, call failed with 400"
        result = sanitize_plan_error(raw, drama_name="测试剧目")

        assert "[开发诊断]" in result
        assert "DeepSeek" in result
        assert "prompt tokens exceeded" in result
        assert "《测试剧目》" in result

    def test_render_error_dev_preserves_raw_details(self, monkeypatch):
        monkeypatch.setenv("AE_FORCE_DEV_ERROR", "1")
        monkeypatch.delenv("AE_FORCE_PROD_ERROR", raising=False)

        raw = "ffmpeg -filter_complex ae_fc_123 failed: libx264 encoder error exit code 1"
        result = sanitize_render_error(raw, drama_name="测试剧目")

        assert "[开发诊断]" in result
        assert "filter_complex" in result
        assert "libx264" in result

    def test_transcribe_warning_dev_untouched(self, monkeypatch):
        monkeypatch.setenv("AE_FORCE_DEV_ERROR", "1")
        monkeypatch.delenv("AE_FORCE_PROD_ERROR", raising=False)

        warning = "SenseVoiceSmall + VAD 模型未缓存，首次需联网下载"
        result = sanitize_transcribe_warning(warning)
        assert result == warning


class TestErrorSanitizerProdMode:
    """In production packaged mode, users must never see model names, LLM references, or raw technical internals."""

    def test_transcribe_error_prod_masks_model_details(self, monkeypatch):
        monkeypatch.delenv("AE_FORCE_DEV_ERROR", raising=False)
        monkeypatch.setenv("AE_FORCE_PROD_ERROR", "1")

        samples = [
            "SenseVoiceSmall pipeline error in funasr.auto.AutoModel",
            "ModuleNotFoundError: No module named 'torch'",
            "ModelScope download failed for Paraformer-zh",
            "ffmpeg decode audio error in C:/temp/1.mp4",
            "未找到视频文件: D:/dramas/episodes",
            "识别返回空结果，无可用文本",
        ]

        for raw in samples:
            sanitized = sanitize_transcribe_error(raw, drama_name="豪门归来")
            # 绝对不能泄露开发诊断标记
            assert "[开发诊断]" not in sanitized
            # 绝对不能泄露底层 ASR / 模型 / 算法库关键词
            assert not _RE_SENSITIVE_ASR.search(sanitized), f"Leaked sensitive word in: {sanitized}"
            assert "《豪门归来》" in sanitized

    def test_plan_error_prod_masks_llm_details(self, monkeypatch):
        monkeypatch.delenv("AE_FORCE_DEV_ERROR", raising=False)
        monkeypatch.setenv("AE_FORCE_PROD_ERROR", "1")

        samples = [
            "DeepSeek API 401 Unauthorized: sk-ant-api03-abcdef123 invalid key",
            "大模型推理超时: Request timed out after 60 seconds",
            "OpenAI LLM prompt token limit reached for model deepseek-chat",
            "未找到剧本台词数据 full_script_data.json，请先识别",
            "策划服务中断：502 Bad Gateway",
            "规则过滤后未产出有效方案",
        ]

        for raw in samples:
            sanitized = sanitize_plan_error(raw, drama_name="豪门归来")
            # 绝对不能泄露开发诊断标记
            assert "[开发诊断]" not in sanitized
            # 绝对不能泄露大模型、DeepSeek、prompt、token 等词汇
            assert not _RE_SENSITIVE_LLM.search(sanitized), f"Leaked LLM sensitive word in: {sanitized}"
            assert "《豪门归来》" in sanitized

    def test_render_error_prod_masks_ffmpeg_details(self, monkeypatch):
        monkeypatch.delenv("AE_FORCE_DEV_ERROR", raising=False)
        monkeypatch.setenv("AE_FORCE_PROD_ERROR", "1")

        samples = [
            "ffmpeg -filter_complex ae_fc_398 failed: Error while opening encoder for output stream #0:0",
            "nvenc encoder error: h264_nvenc init failed",
            "找不到片尾素材: outro.mp4",
            "No space left on device: OSError writing to C:/output/clip.mp4",
            "用户已取消",
        ]

        for raw in samples:
            sanitized = sanitize_render_error(raw, drama_name="豪门归来")
            assert "[开发诊断]" not in sanitized
            assert not _RE_SENSITIVE_RENDER.search(sanitized), f"Leaked render sensitive word in: {sanitized}"
            assert "《豪门归来》" in sanitized

    def test_transcribe_warning_prod_masks_models(self, monkeypatch):
        monkeypatch.delenv("AE_FORCE_DEV_ERROR", raising=False)
        monkeypatch.setenv("AE_FORCE_PROD_ERROR", "1")

        warning1 = "SenseVoiceSmall + VAD 模型未缓存，首次需联网下载（约 300MB）"
        sanitized1 = sanitize_transcribe_warning(warning1)
        assert not _RE_SENSITIVE_ASR.search(sanitized1)
        assert "SenseVoice" not in sanitized1
        assert "VAD" not in sanitized1
        assert "语音识别引擎正在准备中" in sanitized1

        warning2 = "未检测到 CUDA / GPU，将使用 CPU 运行"
        sanitized2 = sanitize_transcribe_warning(warning2)
        assert "未检测到独立显卡加速" in sanitized2
        assert "CUDA" not in sanitized2
