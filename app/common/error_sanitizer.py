"""错误信息环境感知与脱敏模糊化模块。

- 开发环境（is_dev_runtime 为 True）：
  保留完整技术错误与堆栈细节（附加 [开发诊断]），方便快速排查定位。
- 生产打包环境（is_dev_runtime 为 False）：
  彻底过滤所有底层模型名、算法库、AI 提示词、大模型供应商及 FFmpeg 调试信息，
  仅向用户呈现自然、友好、模糊化的业务层提示。
"""

from __future__ import annotations

import re
from typing import Any

from app.common.runtime import is_dev_runtime

# 敏感技术关键词正则匹配（忽略大小写）
_RE_SENSITIVE_ASR = re.compile(
    r"(sensevoice|paraformer|funasr|torch|pytorch|modelscope|onnx|vad|cuda|fbank|sherpa|whisper)",
    re.IGNORECASE,
)
_RE_SENSITIVE_LLM = re.compile(
    r"(deepseek|大模型|llm|openai|chatgpt|prompt|token|api[_\s]?key|sk-[a-zA-Z0-9_-]+|temperature|gpt-)",
    re.IGNORECASE,
)
_RE_SENSITIVE_RENDER = re.compile(
    r"(ffmpeg|ffprobe|filter_complex|ae_fc_|win_run|h264_amf|h264_qsv|h264_nvenc|libx264|subprocess)",
    re.IGNORECASE,
)


def _to_raw_string(error: Any) -> str:
    if isinstance(error, BaseException):
        return str(error).strip() or repr(error)
    return str(error or "").strip()


def _format_error_message(friendly: str, raw: str) -> str:
    """按运行环境格式化错误输出。"""
    if is_dev_runtime():
        clean_raw = raw.strip()
        if clean_raw and clean_raw != friendly:
            return f"{friendly}\n[开发诊断] {clean_raw}"
        return friendly
    return friendly


def sanitize_transcribe_error(error: Any, *, drama_name: str = "") -> str:
    """清洗视频/音频识别（Transcription）阶段报错。"""
    raw = _to_raw_string(error)
    prefix = f"《{drama_name}》" if drama_name else ""

    # 1. 业务已知正常拦截
    if "未找到视频文件" in raw or "未找到待识别" in raw:
        friendly = f"{prefix}未找到视频文件，请检查剧目文件目录"
        return _format_error_message(friendly, raw)

    # 2. 识别无台词 / 内容空
    if "未识别到任何内容" in raw or "无可用文本" in raw or "返回空结果" in raw:
        friendly = f"{prefix}未识别到有效台词，请检查视频音频是否清晰或存在有效人声"
        return _format_error_message(friendly, raw)

    # 3. 核心依赖/模型未就绪
    lower_raw = raw.lower()
    if any(k in lower_raw for k in ("importerror", "modulenotfounderror", "torch", "funasr", "modelscope")):
        friendly = f"{prefix}语音识别核心组件未就绪或加载异常，请重启应用或联系管理员"
        return _format_error_message(friendly, raw)

    # 4. FFmpeg / 音频解码问题
    if "ffmpeg" in lower_raw or "decode" in lower_raw or "audio" in lower_raw:
        friendly = f"{prefix}视频音频解析异常，请检查视频文件是否完整"
        return _format_error_message(friendly, raw)

    # 5. 兜底模糊文案
    friendly = f"{prefix}音频识别遇到异常，请检查视频文件后重试"
    return _format_error_message(friendly, raw)


def sanitize_plan_error(error: Any, *, drama_name: str = "") -> str:
    """清洗剧目策划（Planning）阶段报错。"""
    raw = _to_raw_string(error)
    prefix = f"《{drama_name}》" if drama_name else ""

    # 1. 前置依赖缺失
    if "full_script_data.json" in raw or "未找到剧本" in raw or "请先识别" in raw:
        friendly = f"{prefix}未找到剧本台词数据，请先完成视频识别"
        return _format_error_message(friendly, raw)

    if "未找到视频文件" in raw:
        friendly = f"{prefix}未找到视频文件，请检查剧目文件目录"
        return _format_error_message(friendly, raw)

    # 2. 账号/登录凭据问题
    if any(k in raw for k in ("请先登录", "策划密钥未就绪", "凭据已失效", "401", "Unauthorized")):
        friendly = f"{prefix}登录凭据已失效或策划服务未就绪，请重新登录账号"
        return _format_error_message(friendly, raw)

    # 3. 网络通信 / 超时问题
    lower_raw = raw.lower()
    if any(k in lower_raw for k in ("timeout", "timed out", "connect", "无法连接", "bad gateway", "502", "503", "504")):
        friendly = f"{prefix}网络连接超时，策划方案生成失败，请检查网络后重试"
        return _format_error_message(friendly, raw)

    # 4. 服务端中断/重启
    if "服务重启" in raw or "任务已中断" in raw:
        friendly = f"{prefix}服务重启或任务中断，请重新发起策划"
        return _format_error_message(friendly, raw)

    # 5. 策划规则 / 方案筛选未通过
    if "未产出有效方案" in raw or "未匹配" in raw or "不满足" in raw:
        friendly = f"{prefix}剧本内容暂不满足当前策划规则要求，可调整参数后重试"
        return _format_error_message(friendly, raw)

    # 6. 兜底模糊文案
    friendly = f"{prefix}智能策划方案生成失败，请稍后重试"
    return _format_error_message(friendly, raw)


def sanitize_render_error(error: Any, *, drama_name: str = "") -> str:
    """清洗剪辑渲染（Rendering）阶段报错。"""
    raw = _to_raw_string(error)
    prefix = f"《{drama_name}》" if drama_name else ""

    # 1. 取消动作
    if "已取消" in raw or "cancel" in raw.lower():
        friendly = f"{prefix}渲染已取消"
        return _format_error_message(friendly, raw)

    # 2. 前置依赖缺失
    if "production_plan_v3.json" in raw or "请先完成策划" in raw:
        friendly = f"{prefix}未找到策划方案，请先完成策划"
        return _format_error_message(friendly, raw)

    if "未找到可用于判断画幅" in raw or "未找到视频文件" in raw:
        friendly = f"{prefix}未找到有效的视频文件，请检查剧目文件目录"
        return _format_error_message(friendly, raw)

    if "找不到片尾素材" in raw or "outro" in raw.lower():
        friendly = f"{prefix}缺少必要的片尾素材，请检查素材配置"
        return _format_error_message(friendly, raw)

    # 3. 磁盘 / 写入权限
    lower_raw = raw.lower()
    if "space" in lower_raw or "disk" in lower_raw or "permission" in lower_raw or "oserror" in lower_raw:
        friendly = f"{prefix}成片保存失败，请检查磁盘空间或写入权限"
        return _format_error_message(friendly, raw)

    # 4. 显卡驱动 / 编码异常
    if any(k in lower_raw for k in ("nvenc", "amf", "qsv", "encode", "codec")):
        friendly = f"{prefix}视频合成编码异常，请检查源视频文件或在设置中调整编码配置"
        return _format_error_message(friendly, raw)

    # 5. 兜底模糊文案
    friendly = f"{prefix}视频渲染合成失败，请检查文件后重试"
    return _format_error_message(friendly, raw)


def sanitize_transcribe_warning(warning: str) -> str:
    """清洗环境检查警告文案。"""
    raw = str(warning or "").strip()
    if is_dev_runtime():
        return raw

    # 生产模式脱敏
    if any(k in raw for k in ("SenseVoice", "VAD", "模型未缓存", "下载")):
        return "语音识别引擎正在准备中（首次使用需联网下载，耗时较长，请耐心等待）"
    if any(k in raw for k in ("CUDA", "GPU", "CPU")):
        return "未检测到独立显卡加速，将使用基础处理模式"

    # 若包含底层技术敏感词，抹平
    if _RE_SENSITIVE_ASR.search(raw):
        return "语音识别环境准备中"
    return raw
