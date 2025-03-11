from PySide6.QtCore import QRunnable, QObject, QThreadPool, Qt, Signal


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
            if self.kwargs != {}:
                result = self.func(*self.args, **self.kwargs)
            else:
                result = self.func(*self.args)
            self.signals.finished.emit(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.signals.error.emit(str(e))


class TaskManager(QObject):
    _instance = None

    def __init__(self):
        super().__init__()
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(1)

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = TaskManager()
        return cls._instance

    def submit_task(self, func, args=(), kwargs={},
                    on_success=None, on_error=None):
        # 获取当前是否有任务运行
        if self.thread_pool.activeThreadCount() >= 1:
            raise RuntimeError("请等待当前任务完成")
        """ 提交任务并绑定回调 """
        task = TaskRunnable(func, args, kwargs)
        # 绑定信号到回调（使用队列连接保证线程安全）
        if on_success:
            task.signals.finished.connect(on_success, Qt.QueuedConnection)
        if on_error:
            task.signals.error.connect(on_error, Qt.QueuedConnection)
        self.thread_pool.start(task)  # 将任务提交到线程池


task_manager = TaskManager.instance()
