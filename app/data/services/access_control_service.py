"""桌面端使用权限控制：服务端关闭后随机报错，不暴露封禁原因。"""

from __future__ import annotations

import random

from app.common.config import cfg
from app.common.my_logger import my_logger as logger
from app.data.api.api import get_api

_RANDOM_ERRORS = (
    "网络连接超时，请检查网络后重试",
    "服务暂时不可用，请稍后再试",
    "请求处理失败，请重试",
    "视频资源加载失败",
    "解密模块初始化异常",
    "当前任务队列已满，请稍后重试",
    "文件读写权限不足",
    "依赖组件版本不匹配",
    "内存不足，无法继续处理",
    "上游接口返回异常",
    "编解码器启动失败",
    "临时文件创建失败",
)


class AccessControlService:
    _instance: "AccessControlService | None" = None

    def __init__(self) -> None:
        self._blocked = False

    @classmethod
    def instance(cls) -> "AccessControlService":
        if cls._instance is None:
            cls._instance = AccessControlService()
        return cls._instance

    def is_remote_mode(self) -> bool:
        return True

    def is_blocked(self) -> bool:
        return self._blocked and self.is_remote_mode()

    def block(self) -> None:
        self._blocked = True

    def unblock(self) -> None:
        self._blocked = False

    def random_error(self) -> str:
        return random.choice(_RANDOM_ERRORS)

    def ensure_allowed(self) -> None:
        if self.is_blocked():
            raise RuntimeError(self.random_error())

    def refresh(self) -> bool:
        """刷新封禁状态。

        - 会话有效 → 解封
        - 明确无效 → 封禁
        - 网络/服务不可达 → 保持原状态（避免把连不上 API 误判成封禁）
        """
        if not self.is_remote_mode():
            self.unblock()
            return True
        api = get_api()
        if not hasattr(api, "check_session") and not hasattr(api, "validate_session"):
            return True
        if hasattr(api, "check_session"):
            status = api.check_session()
        else:
            status = "valid" if api.validate_session() else "invalid"

        if status == "valid":
            self.unblock()
            return True
        if status == "invalid":
            self.block()
            return False
        # 不可达：不误封；并解除可能由超时造成的误封，避免业务全卡死
        logger.debug("会话校验暂时不可达，保持可用（不因网络误封禁）")
        self.unblock()
        return True

    def mask_login_error(self, error: str, status_code: int | None = None) -> str:
        if (error or "").strip() == "无效":
            return "无效"
        if status_code == 403 or "登录失败，请稍后重试" in error:
            return self.random_error()
        return error


access_control = AccessControlService.instance()
