"""策划入口：通过服务端代理完成，本地不再调用 LLM。"""

from __future__ import annotations

from typing import Any, Callable

from app.data.models.drama_project import DramaProject
from app.data.services.remote_plan_service import RemotePlanService


class AIDirectorService:
    @staticmethod
    def plan(
        project: DramaProject,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        return RemotePlanService.plan(project, progress_callback=progress_callback)
