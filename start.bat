@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 电子资料室系统
if not exist "%~dp0runtime\python\python.exe" (
    echo [错误] 运行环境缺失: runtime\python\python.exe
    pause
    exit /b 1
)
"%~dp0runtime\python\python.exe" -u "%~dp0launcher.py" start
echo.
pause