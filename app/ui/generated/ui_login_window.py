# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'login_window.ui'
##
## Created by: Qt User Interface Compiler version 6.11.1
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
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout,
    QLabel, QLayout, QSizePolicy, QVBoxLayout,
    QWidget)

from app.ui.components.label_widget import ClickableLabel
from qfluentwidgets import (CheckBox, LineEdit, PasswordLineEdit, PrimaryPushButton,
    PushButton)
import resource_rc

class Ui_Dialog(object):
    def setupUi(self, Dialog):
        if not Dialog.objectName():
            Dialog.setObjectName(u"Dialog")
        Dialog.resize(750, 500)
        icon = QIcon()
        icon.addFile(u":/resource/images/logo.png", QSize(), QIcon.Mode.Normal, QIcon.State.Off)
        Dialog.setWindowIcon(icon)
        Dialog.setStyleSheet(u"")
        self.horizontalLayout = QHBoxLayout(Dialog)
        self.horizontalLayout.setSpacing(0)
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.horizontalLayout.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame(Dialog)
        self.frame.setObjectName(u"frame")
        self.frame.setStyleSheet(u"")
        self.frame.setFrameShape(QFrame.Shape.NoFrame)
        self.frame.setFrameShadow(QFrame.Shadow.Raised)
        self.form = QFrame(self.frame)
        self.form.setObjectName(u"form")
        self.form.setGeometry(QRect(230, 70, 290, 385))
        self.form.setFrameShape(QFrame.Shape.NoFrame)
        self.form.setFrameShadow(QFrame.Shadow.Raised)
        self.horizontalLayout_8 = QHBoxLayout(self.form)
        self.horizontalLayout_8.setObjectName(u"horizontalLayout_8")
        self.horizontalLayout_8.setContentsMargins(20, 10, 20, 20)
        self.verticalLayout_2 = QVBoxLayout()
        self.verticalLayout_2.setSpacing(6)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.login_title = QLabel(self.form)
        self.login_title.setObjectName(u"login_title")
        self.login_title.setMaximumSize(QSize(9999, 40))
        font = QFont()
        font.setFamilies([u"\u9ed1\u4f53"])
        font.setPointSize(18)
        font.setBold(False)
        self.login_title.setFont(font)
        self.login_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.verticalLayout_2.addWidget(self.login_title)

        self.username_label = QLabel(self.form)
        self.username_label.setObjectName(u"username_label")
        font1 = QFont()
        font1.setFamilies([u"Microsoft YaHei"])
        font1.setPointSize(9)
        self.username_label.setFont(font1)

        self.verticalLayout_2.addWidget(self.username_label)

        self.horizontalLayout_9 = QHBoxLayout()
        self.horizontalLayout_9.setSpacing(0)
        self.horizontalLayout_9.setObjectName(u"horizontalLayout_9")
        self.username = LineEdit(self.form)
        self.username.setObjectName(u"username")
        self.username.setMinimumSize(QSize(90, 40))
        font2 = QFont()
        font2.setFamilies([u"Microsoft YaHei"])
        self.username.setFont(font2)
        self.username.setTabletTracking(False)
        self.username.setFrame(False)
        self.username.setClearButtonEnabled(True)

        self.horizontalLayout_9.addWidget(self.username)


        self.verticalLayout_2.addLayout(self.horizontalLayout_9)

        self.password_label = QLabel(self.form)
        self.password_label.setObjectName(u"password_label")
        self.password_label.setFont(font1)

        self.verticalLayout_2.addWidget(self.password_label)

        self.horizontalLayout_10 = QHBoxLayout()
        self.horizontalLayout_10.setSpacing(0)
        self.horizontalLayout_10.setObjectName(u"horizontalLayout_10")
        self.password = PasswordLineEdit(self.form)
        self.password.setObjectName(u"password")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.password.sizePolicy().hasHeightForWidth())
        self.password.setSizePolicy(sizePolicy)
        self.password.setMinimumSize(QSize(90, 40))
        self.password.setBaseSize(QSize(0, 0))
        self.password.setFont(font2)
        self.password.setFrame(False)
        self.password.setClearButtonEnabled(True)

        self.horizontalLayout_10.addWidget(self.password)


        self.verticalLayout_2.addLayout(self.horizontalLayout_10)

        self.horizontalLayout_11 = QHBoxLayout()
        self.horizontalLayout_11.setSpacing(10)
        self.horizontalLayout_11.setObjectName(u"horizontalLayout_11")
        self.horizontalLayout_11.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.horizontalLayout_11.setContentsMargins(-1, -1, 0, -1)
        self.graphic = LineEdit(self.form)
        self.graphic.setObjectName(u"graphic")
        sizePolicy.setHeightForWidth(self.graphic.sizePolicy().hasHeightForWidth())
        self.graphic.setSizePolicy(sizePolicy)
        self.graphic.setMinimumSize(QSize(90, 40))
        self.graphic.setFont(font2)
        self.graphic.setFrame(False)
        self.graphic.setClearButtonEnabled(True)

        self.horizontalLayout_11.addWidget(self.graphic)

        self.image = ClickableLabel(self.form)
        self.image.setObjectName(u"image")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.image.sizePolicy().hasHeightForWidth())
        self.image.setSizePolicy(sizePolicy1)
        self.image.setMinimumSize(QSize(120, 40))
        self.image.setMaximumSize(QSize(80, 40))
        self.image.setFont(font2)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout_11.addWidget(self.image)


        self.verticalLayout_2.addLayout(self.horizontalLayout_11)

        self.horizontalLayout_12 = QHBoxLayout()
        self.horizontalLayout_12.setSpacing(10)
        self.horizontalLayout_12.setObjectName(u"horizontalLayout_12")
        self.horizontalLayout_12.setContentsMargins(-1, -1, 0, -1)
        self.code = LineEdit(self.form)
        self.code.setObjectName(u"code")
        self.code.setMinimumSize(QSize(50, 40))
        self.code.setMaximumSize(QSize(200, 16777215))
        self.code.setFont(font2)
        self.code.setFrame(False)
        self.code.setClearButtonEnabled(True)

        self.horizontalLayout_12.addWidget(self.code)

        self.getCode = PushButton(self.form)
        self.getCode.setObjectName(u"getCode")
        sizePolicy2 = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.getCode.sizePolicy().hasHeightForWidth())
        self.getCode.setSizePolicy(sizePolicy2)
        self.getCode.setMinimumSize(QSize(80, 30))
        self.getCode.setFont(font2)
        self.getCode.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.getCode.setAutoDefault(False)

        self.horizontalLayout_12.addWidget(self.getCode)


        self.verticalLayout_2.addLayout(self.horizontalLayout_12)

        self.horizontalLayout_13 = QHBoxLayout()
        self.horizontalLayout_13.setObjectName(u"horizontalLayout_13")
        self.horizontalLayout_13.setContentsMargins(-1, 0, 0, 0)
        self.session = CheckBox(self.form)
        self.session.setObjectName(u"session")
        self.session.setFont(font1)

        self.horizontalLayout_13.addWidget(self.session)

        self.remember = CheckBox(self.form)
        self.remember.setObjectName(u"remember")
        self.remember.setFont(font1)

        self.horizontalLayout_13.addWidget(self.remember)


        self.verticalLayout_2.addLayout(self.horizontalLayout_13)

        self.login = PrimaryPushButton(self.form)
        self.login.setObjectName(u"login")
        sizePolicy2.setHeightForWidth(self.login.sizePolicy().hasHeightForWidth())
        self.login.setSizePolicy(sizePolicy2)
        self.login.setMinimumSize(QSize(0, 35))
        self.login.setFont(font2)

        self.verticalLayout_2.addWidget(self.login)

        self.verticalLayout_2.setStretch(0, 1)
        self.verticalLayout_2.setStretch(1, 1)
        self.verticalLayout_2.setStretch(2, 1)
        self.verticalLayout_2.setStretch(3, 1)
        self.verticalLayout_2.setStretch(4, 1)
        self.verticalLayout_2.setStretch(5, 1)
        self.verticalLayout_2.setStretch(6, 1)

        self.horizontalLayout_8.addLayout(self.verticalLayout_2)

        self.copyright = QLabel(self.frame)
        self.copyright.setObjectName(u"copyright")
        self.copyright.setGeometry(QRect(265, 460, 220, 31))
        font3 = QFont()
        font3.setFamilies([u"Arial"])
        font3.setPointSize(10)
        self.copyright.setFont(font3)
        self.copyright.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.horizontalLayout.addWidget(self.frame)


        self.retranslateUi(Dialog)

        self.login.setDefault(True)


        QMetaObject.connectSlotsByName(Dialog)
    # setupUi

    def retranslateUi(self, Dialog):
        Dialog.setWindowTitle(QCoreApplication.translate("Dialog", u"\u767b\u5f55", None))
        self.login_title.setText(QCoreApplication.translate("Dialog", u"\u767b\u5f55", None))
        self.username_label.setText(QCoreApplication.translate("Dialog", u"\u6613\u6295\u8d26\u53f7", None))
        self.username.setPlaceholderText(QCoreApplication.translate("Dialog", u"\u8bf7\u8f93\u5165\u8d26\u53f7", None))
        self.password_label.setText(QCoreApplication.translate("Dialog", u"\u6613\u6295\u5bc6\u7801", None))
        self.password.setPlaceholderText(QCoreApplication.translate("Dialog", u"\u8bf7\u8f93\u5165\u5bc6\u7801", None))
        self.graphic.setPlaceholderText(QCoreApplication.translate("Dialog", u"\u9a8c\u8bc1\u7801", None))
        self.image.setText(QCoreApplication.translate("Dialog", u"\u56fe\u7247\u9a8c\u8bc1\u7801\u533a", None))
        self.code.setPlaceholderText(QCoreApplication.translate("Dialog", u"\u77ed\u4fe1\u9a8c\u8bc1\u7801", None))
        self.getCode.setText(QCoreApplication.translate("Dialog", u"\u83b7\u53d6", None))
        self.session.setText(QCoreApplication.translate("Dialog", u"\u81ea\u52a8\u767b\u5f55", None))
        self.remember.setText(QCoreApplication.translate("Dialog", u"\u8bb0\u4f4f\u5bc6\u7801", None))
        self.login.setText(QCoreApplication.translate("Dialog", u"\u767b\u5f55", None))
        self.copyright.setText(QCoreApplication.translate("Dialog", u"\u00a9Copyright \u5728\u914d\u7f6e\u6587\u4ef6\u4fee\u6539", None))
    # retranslateUi

