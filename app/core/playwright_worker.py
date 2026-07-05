"""Playwright 同步 API 专用单线程执行器（避免 QThreadPool 多线程冲突）。"""

from __future__ import annotations

import atexit
import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable

from app.common.my_logger import my_logger as logger


class PlaywrightWorker:
    _instance: PlaywrightWorker | None = None
    _init_lock = threading.Lock()

    def __init__(self) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._thread = threading.Thread(
            target=self._loop, name="PlaywrightWorker", daemon=False
        )
        self._thread.start()

    @classmethod
    def instance(cls) -> PlaywrightWorker:
        if cls._instance is None:
            with cls._init_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            func, args, kwargs, future = item
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                logger.warning("Playwright 任务失败: {}", exc)
                future.set_exception(exc)
            else:
                future.set_result(result)
            finally:
                self._queue.task_done()

    def run(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        future: Future[Any] = Future()
        self._queue.put((func, args, kwargs, future))
        return future.result()

    def shutdown(self) -> None:
        if not self._thread.is_alive():
            return
        self._queue.put(None)
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            logger.warning("PlaywrightWorker 未在 5s 内结束，可能仍有 Playwright 任务进行中")


class _PlaywrightWorkerProxy:
    """延迟创建 PlaywrightWorker，仅在首次使用时启动后台线程。"""

    def run(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return PlaywrightWorker.instance().run(func, *args, **kwargs)


playwright_worker = _PlaywrightWorkerProxy()


def shutdown_playwright_worker() -> None:
    """应用退出时调用，结束 PlaywrightWorker 后台线程。"""
    worker = PlaywrightWorker._instance
    if worker is None:
        return
    worker.shutdown()
    PlaywrightWorker._instance = None


atexit.register(shutdown_playwright_worker)
