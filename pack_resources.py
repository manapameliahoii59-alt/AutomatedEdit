# -*- coding: utf-8 -*-
# 用于运行前编译pyside的资源文件和ui文件
import os

os.system("pyside6-rcc resource/resource.qrc -o resource_rc.py")  # 编译资源文件
ui_dirs = ["view", "ui_page"]
for ui_dir in ui_dirs:
    for file in os.listdir(ui_dir):
        if file.endswith(".ui"):
            os.system("pyside6-uic -o %s/ui_%s.py %s/%s" % (ui_dir, file[:-3], ui_dir, file))  # 编译ui文件
