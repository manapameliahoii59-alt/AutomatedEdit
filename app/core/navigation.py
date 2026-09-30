from typing import Callable
from PySide6.QtWidgets import QWidget

class LazyViewProxy(QWidget):
    """A proxy widget that loads the real view content only when shown."""
    def __init__(self, factory: Callable[[], QWidget], object_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self._factory = factory
        self._real_view = None
        self._loaded = False
        
        # Layout to hold the real view
        from PySide6.QtWidgets import QVBoxLayout
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0,0,0,0)

    def ensure_loaded(self) -> QWidget:
        if not self._loaded:
            self._real_view = self._factory()
            self._layout.addWidget(self._real_view)
            self._loaded = True
        return self._real_view
        
    def showEvent(self, event):
        self.ensure_loaded()
        super().showEvent(event)
        
    def __getattr__(self, name):
        # Forward attribute access to real view if possible (tricky with inheritance)
        if self._real_view:
            return getattr(self._real_view, name)
        raise AttributeError(f"'LazyViewProxy' object has no attribute '{name}'")
