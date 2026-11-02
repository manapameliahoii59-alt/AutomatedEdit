@echo off
cd /d "%~dp0"
title AutomatedEdit Publish Release
chcp 65001 >nul

echo ============================================================
echo   Publish installer to Tencent COS
echo ============================================================
echo.

if "%~1"=="" (
    echo   This will upload release\*.exe to COS and update version.json
    echo   Press any key to continue, or Ctrl+C to cancel.
    echo.
    pause >nul
    echo.
)

where uv >nul 2>nul
if errorlevel 1 goto use_python

echo [Using uv: first run will download cos-python-sdk-v5]
echo.
uv run --no-project --with cos-python-sdk-v5 python scripts\publish_release.py %*
goto done

:use_python
echo [uv not found, using current python environment]
echo.
python scripts\publish_release.py %*

:done
if errorlevel 1 (
    echo.
    echo [Publish failed. Please check the error message above.]
) else (
    echo.
    echo [Publish finished. Remember to sync release\version.json to the server.]
)

echo.
pause
