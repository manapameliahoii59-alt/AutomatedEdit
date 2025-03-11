# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'page_two.ui'
##
## Created by: Qt User Interface Compiler version 6.7.0
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QSizePolicy, QWidget)

from qfluentwidgets import PushButton

class Ui_page_two(object):
    def setupUi(self, page_two):
        if not page_two.objectName():
            page_two.setObjectName(u"page_two")
        page_two.resize(723, 456)
        self.pushButton = PushButton(page_two)
        self.pushButton.setObjectName(u"pushButton")
        self.pushButton.setGeometry(QRect(290, 190, 111, 31))

        self.retranslateUi(page_two)

        QMetaObject.connectSlotsByName(page_two)
    # setupUi

    def retranslateUi(self, page_two):
        page_two.setWindowTitle(QCoreApplication.translate("page_two", u"Form", None))
        self.pushButton.setText(QCoreApplication.translate("page_two", u"\u6d4b\u8bd5\u6309\u94ae", None))
    # retranslateUi

