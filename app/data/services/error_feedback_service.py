"""桌面端错误反馈采集与上报服务。"""

from __future__ import annotations

import collections
from dataclasses import dataclass, field
import platform
import sys
import threading
import time
import traceback
from typing import Any

from app.common.config import VERSION
from app.common.my_logger import my_logger as logger
from app.data.api.api import get_api


def get_client_environment_summary() -> str:
    """采集桌面端基础硬件与环境信息（用于排查）。"""
    parts = [
        f"OS: {platform.platform()}",
        f"Python: {platform.python_version()} ({sys.executable})",
    ]
    # Windows 下 PySide6 先加载时动态 import torch 会导致 WinError 1114/访问冲突
    # 故仅当 sys.modules 中已存在 torch（如 entry.py 启动时已优先导入）时读取
    torch = sys.modules.get("torch")
    if torch is not None:
        try:
            cuda_ok = torch.cuda.is_available()
            gpu_name = torch.cuda.get_device_name(0) if cuda_ok else "None"
            parts.append(f"PyTorch: {torch.__version__} (CUDA: {cuda_ok}, GPU: {gpu_name})")
        except Exception:
            pass
    return " | ".join(parts)


@dataclass
class ErrorReportData:
    error_stage: str
    drama_name: str
    friendly_msg: str
    raw_error: str
    app_version: str = VERSION
    client_info: str = field(default_factory=get_client_environment_summary)
    timestamp: float = field(default_factory=time.time)
    submitted: bool = False


class ErrorFeedbackService:
    """集中记录桌面端运行异常，配合 UI 弹窗提供一键上报功能。"""

    def __init__(self, max_history: int = 20) -> None:
        self._history: collections.deque[ErrorReportData] = collections.deque(maxlen=max_history)
        self._latest_report: ErrorReportData | None = None
        # 去重：同一条错误文案在窗口期内只自动上报一次
        self._recent_submitted: dict[str, float] = {}
        self._submit_lock = threading.Lock()

    def record_error(
        self,
        stage: str,
        drama_name: str,
        friendly_msg: str,
        raw_error: Any,
    ) -> ErrorReportData:
        """记录一条真实的异常信息。"""
        raw_text = ""
        if isinstance(raw_error, BaseException):
            if raw_error.__traceback__:
                raw_text = "".join(
                    traceback.format_exception(type(raw_error), raw_error, raw_error.__traceback__)
                ).strip()
            else:
                raw_text = str(raw_error).strip() or repr(raw_error)
        else:
            raw_text = str(raw_error or "").strip()

        # 如果当前栈中有未捕获的活跃 traceback，尝试捕获更深的技术细节
        cur_exc = traceback.format_exc()
        if cur_exc and "NoneType: None" not in cur_exc and cur_exc.strip() not in raw_text:
            raw_text = f"{raw_text}\n\n[Active Traceback]:\n{cur_exc}".strip()

        if not raw_text:
            raw_text = "未知异常（无详细堆栈）"

        report = ErrorReportData(
            error_stage=stage or "general",
            drama_name=drama_name or "",
            friendly_msg=friendly_msg or "",
            raw_error=raw_text,
        )
        self._history.append(report)
        self._latest_report = report
        logger.info(
            "已记录错误反馈项: stage={}, drama={}, len(raw)={}",
            stage,
            drama_name,
            len(raw_text),
        )
        return report

    def get_latest_report(self) -> ErrorReportData | None:
        return self._latest_report

    def find_matching_report(
        self,
        content: str = "",
        max_age_seconds: float = 60.0,
    ) -> ErrorReportData | None:
        """根据弹窗内容或最近发生时间找到对应的待反馈错误。"""
        now = time.time()
        clean_content = (content or "").strip()

        # 优先倒序匹配弹窗内容
        for rep in reversed(self._history):
            if now - rep.timestamp > max_age_seconds:
                continue
            if rep.submitted:
                continue
            if clean_content:
                if rep.friendly_msg and (rep.friendly_msg in clean_content or clean_content in rep.friendly_msg):
                    return rep
                if rep.drama_name and rep.drama_name in clean_content:
                    return rep

        # 兜底：如果最近 60s 内有未上报的异常，且弹窗含有常见报错特征
        if self._latest_report and not self._latest_report.submitted:
            if now - self._latest_report.timestamp <= max_age_seconds:
                if clean_content and any(
                    k in clean_content for k in ("失败", "异常", "错误", "未就绪", "超时", "重试", "取消")
                ):
                    return self._latest_report

        return None

    def submit_report(self, report: ErrorReportData) -> tuple[bool, str]:
        """将错误反馈提交至服务端。"""
        payload = {
            "app_version": report.app_version,
            "error_stage": report.error_stage,
            "drama_name": report.drama_name,
            "friendly_msg": report.friendly_msg,
            "raw_error": report.raw_error,
            "client_info": report.client_info,
        }
        try:
            api = get_api()
            res = api.post_error_report(payload)
            report.submitted = True
            logger.info("错误反馈成功上报至服务器: id={}", res.get("id"))
            return True, ""
        except Exception as e:
            msg = str(e) or "网络连接异常"
            logger.warning("上报错误反馈失败: {}", msg)
            return False, msg

    def _is_recently_submitted(self, key: str, now: float, window: float) -> bool:
        ts = self._recent_submitted.get(key)
        return ts is not None and (now - ts) < window

    def _prune_recent_submitted(self, now: float, window: float) -> None:
        expired = [key for key, ts in self._recent_submitted.items() if now - ts >= window]
        for key in expired:
            self._recent_submitted.pop(key, None)

    def submit_matching_report(
        self,
        content: str = "",
        *,
        max_age_seconds: float = 60.0,
        dedupe_seconds: float = 60.0,
    ) -> bool:
        """查找并自动上报与文案匹配的异常；同内容在去重窗口内只上报一次。

        供非阻塞弱提示复用：命中已记录的异常才上报，业务提示类文案不会上报。
        """
        with self._submit_lock:
            report = self.find_matching_report(content, max_age_seconds=max_age_seconds)
            if report is None:
                return False

            key = (report.friendly_msg or content or "").strip()
            now = time.time()
            if key and self._is_recently_submitted(key, now, dedupe_seconds):
                logger.info("错误反馈去重跳过（{} 秒内已上报）: {}", dedupe_seconds, key)
                return False

            ok, _msg = self.submit_report(report)
            if ok and key:
                self._recent_submitted[key] = now
                self._prune_recent_submitted(now, dedupe_seconds)
            return ok


error_feedback_service = ErrorFeedbackService()
