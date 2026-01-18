from PySide6.QtCore import Qt, QPoint
from qfluentwidgets import InfoBar, FluentIcon, IndeterminateProgressRing, InfoBarIcon, FluentStyleSheet, InfoBarManager


@InfoBarManager.register('Custom')
class CustomInfoBarManager(InfoBarManager):
    def _pos(self, infoBar: InfoBar, parentSize=None):
        p = infoBar.parent()
        parentSize = parentSize or p.size()
        x = (parentSize.width() - infoBar.width()) // 2
        y = 40
        return QPoint(x, y)

    def _slideStartPos(self, infoBar: InfoBar):
        pos = self._pos(infoBar)
        return QPoint(pos.x(), pos.y() - 16)


class ProgressInfoBar(InfoBar):
    def __init__(self, title, content, parent):
        super().__init__(icon=FluentIcon.SYNC,
                         title=title,
                         content=content,
                         orient=Qt.Horizontal,
                         isClosable=True,
                         position='Custom',
                         duration=-1, parent=parent)

        self.spinner = IndeterminateProgressRing()
        self.spinner.setFixedSize(22, 22)
        self.spinner.setStrokeWidth(3)
        self.hBoxLayout.setContentsMargins(12, 8, 8, 8)
        self.hBoxLayout.setSpacing(8)
        self.textLayout.setSpacing(0)
        self.iconWidget.deleteLater()
        self.hBoxLayout.insertWidget(0, self.spinner)
        self.setProperty('type', InfoBarIcon.SUCCESS.value)
        FluentStyleSheet.INFO_BAR.apply(self)
