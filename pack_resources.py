# -*- coding: utf-8 -*-
# 用于运行前编译pyside的资源文件和ui文件
import os
import site

# 找到site-packages目录
site_packages_path = site.getsitepackages()[-1]
# 找到pyside6的lrelease.exe的路径
lr = 'lrelease.exe' if os.name == 'nt' else 'lrelease'
lrelease_path = os.path.join(site_packages_path, 'PySide6', lr)
os.system(f'{lrelease_path} -verbose resource/i18n/zh.ts -qm resource/i18n/zh.qm')  # 编译翻译文件
os.system("pyside6-rcc resource/resource.qrc -o resource_rc.py")  # 编译资源文件

# Compile UI files in app/ui/generated
ui_dir = 'app/ui/generated'
if os.path.exists(ui_dir):
    ui_files = os.listdir(ui_dir)
    for ui_file in ui_files:
        if ui_file.endswith('.ui'):
            # Standardize naming: page_one.ui -> ui_page_one.py
            # But wait, previous naming was inconsistent:
            # ui_view/login_window.ui -> ui_view/ui_login_window.py
            # ui_page/page_one.ui -> ui_page/ui_page_one.py (Wait, was it ui_page_one.py or ui_page_one.py?)
            # Let's check the old code logic:
            # output = f"ui_page/ui_{ui_file.split('.')[0]}.py"
            # So page_one.ui becomes ui_page_one.py
            
            # For login_window.ui, it was in ui_view, output was ui_view/ui_login_window.py
            # So the rule is: prepend "ui_" to the filename.
            
            output_name = f"ui_{ui_file.split('.')[0]}.py"
            output_path = os.path.join(ui_dir, output_name)
            input_path = os.path.join(ui_dir, ui_file)
            
            print(f"Compiling {input_path} -> {output_path}")
            os.system(f"pyside6-uic {input_path} -o {output_path}")
