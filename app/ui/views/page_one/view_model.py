from PySide6.QtCore import Signal
from app.core.view_model import ViewModel
from app.core.task_manager import task_manager
from app.data.api.api import demo_api

class PageOneViewModel(ViewModel):
    loadingChanged = Signal(bool)
    messageReceived = Signal(str)
    errorOccurred = Signal(str)

    def do_something(self):
        self.messageReceived.emit("do something")

    def do_something_async(self):
        self.loadingChanged.emit(True)
        task_manager.submit_task(
            demo_api.sleep, args=(2,),
            on_success=self._on_async_success,
            on_error=self._on_error
        )

    def _on_async_success(self, result):
        self.loadingChanged.emit(False)
        self.messageReceived.emit("do something async success")

    def _on_error(self, error):
        self.loadingChanged.emit(False)
        self.errorOccurred.emit(str(error))
