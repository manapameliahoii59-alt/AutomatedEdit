<h1 align="center">
  PySide6 Fluent Design模板
</h1>

<p align="center">
  配合qt designer使用，基于pyqt-fluent-widgets的模板
</p>

## 简介

本项目基于[PyQt-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets/), 为了方便像我这样的新手使用，将其封装成了一个模板，带有日志记录模块，
密码保存、简单实现了登录界面和主界面的切换，异步操作，可以直接使用qt designer进行界面设计，然后专注写业务代码。

<strong>注意：由于本人仅仅为编程爱好者，并非职业程序员，代码质量很差，此项目仅做参考。</strong>

## 登录界面

<img src="https://github.com/Cheukfung/pyqt-fluent-widgets-template/blob/pyside6/screen_shot/login.png?raw=true">

## 主界面
<img src="https://github.com/Cheukfung/pyqt-fluent-widgets-template/blob/pyside6/screen_shot/main_window.png?raw=true">
<img src="https://github.com/Cheukfung/pyqt-fluent-widgets-template/blob/pyside6/screen_shot/main_dark.png?raw=true">


## 使用方法
### ui编辑
<img src="https://github.com/Cheukfung/pyqt-fluent-widgets-template/blob/pyqt5/example%20image/qt%20desinger.png?raw=true">
clone项目到本地，打开ui_page目录，里面共有2个页面，使用qt-designer打开，使用时只需要把相应的控件添加到对应的页面即可。
### 绑定控件事件
参考 view/pages/page_one.py和view/pages/page_one_handler.py, 在page_one_handler.py中添加对应的事件处理函数，然后在page_one.py中绑定对应的控件事件。

## 添加页面
如果需要添加页面，在ui_page添加页面，然后在view/pages/中参考page_one.py添加对应的页面、参考page_one_handler.py中添加对应的事件处理函数。

## 修改样式文件

修改resource/qss/里面对应的qss文件即可

## 运行

安装好依赖项目后，先执行pack_resources.py文件，将资源文件打包到resource.qrc文件中，然后运行entry.py文件即可。

## 打包

确保安装好nuitka，然后运行build.py,即可打包成exe文件。

