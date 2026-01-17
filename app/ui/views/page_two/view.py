from PySide6.QtWidgets import QWidget
from ui_page.ui_page_two import Ui_page_two

class PageTwo(QWidget, Ui_page_two):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
