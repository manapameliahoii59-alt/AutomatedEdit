@echo off
cd /d "%~dp0"
title AutomatedEdit Server Deploy

python scripts\deploy_server.py %*

if errorlevel 1 (
    echo.
    echo [Deploy failed. Please check the error message above.]
)

echo.
pause
