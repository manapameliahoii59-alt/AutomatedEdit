from PySide6.QtCore import QRunnable, QObject, QThreadPool, Qt, Signal
import traceback

class TaskSignals(QObject):
    finished = Signal(object)
    error = Signal(str)

class TaskRunnable(QRunnable):
    def __init__(self, func, args=(), kwargs={}):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.signals = TaskSignals()
        self.setAutoDelete(True)

    def run(self):
        try:
            if self.kwargs:
                result = self.func(*self.args, **self.kwargs)
            else:
                result = self.func(*self.args)
            self.signals.finished.emit(result)
        except Exception as e:
            error_msg = "".join(traceback.format_exception(None, e, e.__traceback__))
            print(error_msg) # Consider logging this instead
            self.signals.error.emit(str(e))

class TaskManager(QObject):
    _instance = None

    def __init__(self):
        super().__init__()
        self.thread_pool = QThreadPool.globalInstance()
        # Default to ideal thread count (usually core count)
        # self.thread_pool.setMaxThreadCount(QThreadPool.globalInstance().maxThreadCount()) 
        # No need to set explicitly if we want default behavior, but let's ensure it's not 1.

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = TaskManager()
        return cls._instance

    def submit_task(self, func, args=(), kwargs={}, on_success=None, on_error=None):
        """ 
        Submit a task to the thread pool.
        
        Args:
            func: The function to execute.
            args: Positional arguments for the function.
            kwargs: Keyword arguments for the function.
            on_success: Callback function for successful completion.
            on_error: Callback function for error handling.
        """
        task = TaskRunnable(func, args, kwargs)
        
        if on_success:
            task.signals.finished.connect(on_success, Qt.QueuedConnection)
        if on_error:
            task.signals.error.connect(on_error, Qt.QueuedConnection)
            
        self.thread_pool.start(task)

task_manager = TaskManager.instance()
