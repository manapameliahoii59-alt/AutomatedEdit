from PySide6.QtWidgets import QWidget

from ui_page.ui_page_one import Ui_page_one


# 从ui文件生成的Ui_page_one类继承
class PageOne(QWidget, Ui_page_one):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

