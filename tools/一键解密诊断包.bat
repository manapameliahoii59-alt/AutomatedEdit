@echo off
chcp 65001 >nul
title 剪辑助手 (AutomatedEdit) 诊断包一键解密工具

cd /d "%~dp0\.."

if "%~1"=="" (
    echo ======================================================================
    echo  【AutomatedEdit 错误诊断包解密工具】
    echo ======================================================================
    echo.
    echo  使用提示：
    echo  请直接将客户发送给您的 [error.aedump] 或 [crash.aedump] 文件，
    echo  用鼠标拖拽并松手扔到本 bat 图标上！
    echo.
    echo ======================================================================
    pause
    exit /b 1
)

echo 正在解密排查文件: %~1 ...
echo 私钥读取位置: Desktop\AE_Diagnostic_Key\private_key.pem
echo.

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "tools\decrypt_error.py" "%~1"
) else (
    uv run python "tools\decrypt_error.py" "%~1"
)

echo.
pause
