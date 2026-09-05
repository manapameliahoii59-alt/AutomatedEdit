"""策划入口：默认统一走服务端（通道/Key 由管理后台按用户配置）；
开发环境设 AE_LOCAL_PLAN=1 时可本地直调。"""

from __future__ import annotations

import threading
from typing import Any, Callable

from app.data.models.drama_project import DramaProject
from app.data.services.local_plan_service import LocalPlanService, use_local_plan
from app.data.services.remote_plan_service import RemotePlanService

_plan_lock = threading.RLock()


class AIDirectorService:
    @staticmethod
    def plan(
        project: DramaProject,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        # 批量/并行入口统一串行，避免多剧同时打策划 API、进度与日志交错
        with _plan_lock:
            if use_local_plan():
                return LocalPlanService.plan(project, progress_callback=progress_callback)
            return RemotePlanService.plan(project, progress_callback=progress_callback)
