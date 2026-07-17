"""全局渲染队列：多部剧串行执行，避免并发占满 CPU。"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QCoreApplication, QObject, Qt, Signal

from app.common.my_logger import my_logger as logger

CANCEL_MESSAGE = "渲染已取消"


class _RenderQueueSignals(QObject):
    """主线程信号桥：工作线程完成后投递到 GUI 线程。"""

    succeeded = Signal(object)  # result
    failed = Signal(str)  # message


class RenderQueue:
    """全局渲染队列：多部剧渲染串行执行，避免并发占用资源。"""

    _instance: RenderQueue | None = None

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
        self._cancel_event = threading.Event()
        self._active_proc = None
        self._proc_lock = threading.Lock()
        self._lock = threading.Lock()
        self._current_on_success: Callable[[Any], None] | None = None
        self._current_on_error: Callable[[str], None] | None = None
        # 延迟到 QApplication 就绪后再创建，避免 import 阶段建 QObject 导致跨线程信号丢失
        self._signals: _RenderQueueSignals | None = None
        self._signals_lock = threading.Lock()

    @classmethod
    def instance(cls) -> "RenderQueue":
        if cls._instance is None:
            cls._instance = RenderQueue()
        return cls._instance

    def _ensure_signals(self) -> _RenderQueueSignals:
        with self._signals_lock:
            if self._signals is not None:
                return self._signals
            signals = _RenderQueueSignals()
            app = QCoreApplication.instance()
            if app is not None:
                signals.moveToThread(app.thread())
            signals.succeeded.connect(self._on_succeeded, Qt.QueuedConnection)
            signals.failed.connect(self._on_failed, Qt.QueuedConnection)
            self._signals = signals
            return signals

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def is_busy(self) -> bool:
        with self._lock:
            return self._running or bool(self._pending)

    def register_proc(self, proc) -> None:
        with self._proc_lock:
            self._active_proc = proc

    def request_cancel(self) -> None:
        self._cancel_event.set()
        with self._proc_lock:
            proc = self._active_proc
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
        with self._lock:
            pending = list(self._pending)
            self._pending.clear()
        for _, _, on_error, _ in pending:
            if on_error:
                try:
                    on_error(CANCEL_MESSAGE)
                except Exception:
                    logger.exception("取消排队任务回调异常")

    def submit(
        self,
        func: Callable[[], Any],
        *,
        on_success: Callable[[Any], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_start: Callable[[], None] | None = None,
    ) -> bool:
        """提交渲染任务。返回 True 表示立刻开始，False 表示进入排队。"""
        self._ensure_signals()
        with self._lock:
            was_busy = self._running or bool(self._pending)
            self._pending.append((func, on_success, on_error, on_start))
            should_start = not self._running
            if should_start:
                self._cancel_event.clear()
            pending_count = len(self._pending)
        logger.debug(
            "渲染队列提交: immediate={} pending={}",
            not was_busy,
            pending_count,
        )
        if should_start:
            self._run_next()
        return not was_busy

    def _run_next(self) -> None:
        with self._lock:
            if not self._pending:
                self._running = False
                self._current_on_success = None
                self._current_on_error = None
                with self._proc_lock:
                    self._active_proc = None
                logger.debug("渲染队列空闲")
                return

            if self._cancel_event.is_set():
                pending = list(self._pending)
                self._pending.clear()
                self._running = False
                self._current_on_success = None
                self._current_on_error = None
                with self._proc_lock:
                    self._active_proc = None
            else:
                pending = None
                self._running = True
                func, on_success, on_error, on_start = self._pending.popleft()
                self._current_on_success = on_success
                self._current_on_error = on_error
                left = len(self._pending)

        if pending is not None:
            for _, _, cb, _ in pending:
                if cb:
                    try:
                        cb(CANCEL_MESSAGE)
                    except Exception:
                        logger.exception("取消排队任务回调异常")
            return

        logger.debug("渲染队列开始下一部，剩余排队 {}", left)
        if on_start:
            try:
                on_start()
            except Exception:
                logger.exception("渲染启动回调异常")

        signals = self._ensure_signals()

        def worker() -> None:
            try:
                result = func()
            except Exception as exc:
                logger.debug("渲染任务异常: {}", exc, exc_info=True)
                signals.failed.emit(str(exc))
                return
            logger.debug("渲染工作线程结束，投递成功回调到主线程")
            signals.succeeded.emit(result)

        threading.Thread(target=worker, name="RenderWorker", daemon=True).start()

    def _on_succeeded(self, result: Any) -> None:
        logger.debug("渲染成功回调进入主线程")
        on_success = self._current_on_success
        # 回调里会查 is_busy()；若无后续任务，先清 running，避免进度条关不掉
        with self._lock:
            if not self._pending:
                self._running = False
        try:
            if on_success:
                on_success(result)
        except Exception:
            logger.exception("渲染成功回调异常，继续队列中的下一部")
        finally:
            self._run_next()

    def _on_failed(self, message: str) -> None:
        logger.debug("渲染失败回调进入主线程: {}", message)
        on_error = self._current_on_error
        with self._lock:
            if not self._pending:
                self._running = False
        try:
            if on_error:
                on_error(message)
        except Exception:
            logger.exception("渲染失败回调异常，继续队列中的下一部")
        finally:
            self._run_next()


# 仅创建逻辑容器；Qt 信号在首次 submit 时再绑到主线程
render_queue = RenderQueue.instance()
