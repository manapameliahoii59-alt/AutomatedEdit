from PySide6.QtWidgets import QWidget
from common.utils import show_dialog
from components.bar import ProgressInfoBar
from ui_page.ui_page_one import Ui_page_one
from .view_model import PageOneViewModel

class PageOne(QWidget, Ui_page_one):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.loading_bar = None
        self.vm = PageOneViewModel(self)
        self.setupUi(self)
        self.bind_event()
        self.bind_view_model()

    def bind_event(self):
        self.pushButton.clicked.connect(self.vm.do_something)
        self.pushButton_2.clicked.connect(self.vm.do_something_async)

    def bind_view_model(self):
        self.vm.loadingChanged.connect(self._handle_loading)
        self.vm.messageReceived.connect(lambda msg: show_dialog(self, msg, '提示'))
        self.vm.errorOccurred.connect(self.on_common_error)

    def _handle_loading(self, is_loading):
        if is_loading:
            self.show_state_tooltip('正在加载', '请稍后...')
        else:
            self.close_state_tooltip()

    def show_state_tooltip(self, title, content):
        self.loading_bar = ProgressInfoBar(title, content, self)
        self.loading_bar.show()

    def close_state_tooltip(self):
        if self.loading_bar:
            self.loading_bar.hide()
            self.loading_bar = None

    def on_common_error(self, msg):
        show_dialog(self, msg, '提示')
