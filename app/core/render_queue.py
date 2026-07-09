from collections import deque
from collections.abc import Callable
from typing import Any

from app.core.task_manager import task_manager


class RenderQueue:
    """全局渲染队列：多部剧渲染串行执行，避免并发占用资源。"""

    _instance = None

    def __init__(self) -> None:
        self._pending: deque[
            tuple[
                Callable[[], Any],
                Callable[[Any], None] | None,
                Callable[[str], None] | None,
                Callable[[], None] | None,
            ]
        ] = deque()
        self._running = False

    @classmethod
    def instance(cls) -> "RenderQueue":
        if cls._instance is None:
            cls._instance = RenderQueue()
        return cls._instance

    def submit(
        self,
        func: Callable[[], Any],
        *,
        on_success: Callable[[Any], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_start: Callable[[], None] | None = None,
    ) -> None:
        self._pending.append((func, on_success, on_error, on_start))
        if not self._running:
            self._run_next()

    def _run_next(self) -> None:
        if not self._pending:
            self._running = False
            return

        self._running = True
        func, on_success, on_error, on_start = self._pending.popleft()
        if on_start:
            on_start()

        def _done(result: Any) -> None:
            if on_success:
                on_success(result)
            self._run_next()

        def _fail(msg: str) -> None:
            if on_error:
                on_error(msg)
            self._run_next()

        task_manager.submit_task(func, on_success=_done, on_error=_fail)


render_queue = RenderQueue.instance()
