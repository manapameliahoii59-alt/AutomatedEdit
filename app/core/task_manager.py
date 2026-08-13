from PySide6.QtCore import QRunnable, QObject, QThreadPool, Qt, Signal

from app.common.my_logger import my_logger as logger
from app.data.services.access_control_service import access_control


class TaskSignals(QObject):
    finished = Signal(object)
    error = Signal(str)


class TaskRunnable(QRunnable):
    def __init__(self, func, args=(), kwargs=None, *, check_access: bool = True):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs or {}
        self.check_access = check_access
        self.signals = TaskSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            if self.check_access:
                # 误封后的探活放在 worker，避免 submit_task 阻塞 UI
                if access_control.is_blocked():
                    access_control.refresh()
                access_control.ensure_allowed()
            result = self.func(*self.args, **self.kwargs)
            self.signals.finished.emit(result)
        except Exception as e:
            msg = str(e).strip() or f"{type(e).__name__}（无详细信息）"
            logger.debug("后台任务异常: {}", msg, exc_info=True)
            self.signals.error.emit(msg)


class TaskManager(QObject):
    _instance = None

    def __init__(self):
        super().__init__()
        self.thread_pool = QThreadPool.globalInstance()
        # Keep TaskSignals alive until queued callbacks run. QRunnable AutoDelete
        # would otherwise drop the only ref and discard pending finished/error.
        self._live_signals: set[TaskSignals] = set()

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = TaskManager()
        return cls._instance

    def submit_task(
        self,
        func,
        args=(),
        kwargs=None,
        on_success=None,
        on_error=None,
        *,
        check_access: bool = True,
    ):
        """
        Submit a task to the thread pool.

        Args:
            func: The function to execute.
            args: Positional arguments for the function.
            kwargs: Keyword arguments for the function.
            on_success: Callback function for successful completion.
            on_error: Callback function for error handling.
            check_access: 为 False 时跳过桌面端封禁检查（用于登录等恢复会话的任务）。
        """
        if kwargs is None:
            kwargs = {}

        task = TaskRunnable(func, args, kwargs, check_access=check_access)
        signals = task.signals
        # Own signals on the main-thread TaskManager so they outlive the runnable.
        signals.setParent(self)
        self._live_signals.add(signals)

        def _cleanup():
            self._live_signals.discard(signals)
            signals.deleteLater()

        def _finished(result):
            try:
                if on_success:
                    on_success(result)
            finally:
                _cleanup()

        def _errored(msg):
            try:
                if on_error:
                    on_error(msg)
            finally:
                _cleanup()

        signals.finished.connect(_finished, Qt.QueuedConnection)
        signals.error.connect(_errored, Qt.QueuedConnection)

        self.thread_pool.start(task)


task_manager = TaskManager.instance()
