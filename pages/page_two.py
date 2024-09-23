from PySide6.QtWidgets import QWidget

from ui_page.ui_page_two import Ui_page_two


# 从ui文件生成的Ui_page_one类继承
class PageTwo(QWidget, Ui_page_two):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
