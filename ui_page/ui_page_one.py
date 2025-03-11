# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'page_one.ui'
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

class Ui_page_one(object):
    def setupUi(self, page_one):
        if not page_one.objectName():
            page_one.setObjectName(u"page_one")
        page_one.resize(723, 456)
        self.pushButton = PushButton(page_one)
        self.pushButton.setObjectName(u"pushButton")
        self.pushButton.setGeometry(QRect(280, 120, 111, 31))
        self.pushButton_2 = PushButton(page_one)
        self.pushButton_2.setObjectName(u"pushButton_2")
        self.pushButton_2.setGeometry(QRect(280, 190, 111, 31))

        self.retranslateUi(page_one)

        QMetaObject.connectSlotsByName(page_one)
    # setupUi

    def retranslateUi(self, page_one):
        page_one.setWindowTitle(QCoreApplication.translate("page_one", u"Form", None))
        self.pushButton.setText(QCoreApplication.translate("page_one", u"\u6d4b\u8bd5\u6309\u94ae", None))
        self.pushButton_2.setText(QCoreApplication.translate("page_one", u"\u8017\u65f6\u64cd\u4f5c\u6f14\u793a", None))
    # retranslateUi

