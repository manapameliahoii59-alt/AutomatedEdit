from PySide6.QtCore import QRunnable, QObject, QThreadPool, Qt, Signal

from app.common.my_logger import my_logger as logger
from app.data.services.access_control_service import access_control


class TaskSignals(QObject):
    finished = Signal(object)
    error = Signal(str)


class TaskRunnable(QRunnable):
    def __init__(self, func, args=(), kwargs=None):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs or {}
        self.signals = TaskSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            access_control.ensure_allowed()
            result = self.func(*self.args, **self.kwargs)
            self.signals.finished.emit(result)
        except Exception as e:
            logger.debug("后台任务异常: {}", e, exc_info=True)
            self.signals.error.emit(str(e))


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

    def submit_task(self, func, args=(), kwargs=None, on_success=None, on_error=None):
        """
        Submit a task to the thread pool.

        Args:
            func: The function to execute.
            args: Positional arguments for the function.
            kwargs: Keyword arguments for the function.
            on_success: Callback function for successful completion.
            on_error: Callback function for error handling.
        """
        if kwargs is None:
            kwargs = {}

        if access_control.is_blocked():
            # 若此前因网络抖动被误封，再探活一次；仍封禁才拒绝
            access_control.refresh()
        if access_control.is_blocked():
            message = access_control.random_error()
            if on_error:
                on_error(message)
            return

        task = TaskRunnable(func, args, kwargs)
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
