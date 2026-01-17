from PySide6.QtCore import QObject

class ViewModel(QObject):
    """Base class for all ViewModels."""
    def __init__(self, parent=None):
        super().__init__(parent)
