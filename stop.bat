@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 电子资料室系统 - 停止
"%~dp0runtime\python\python.exe" -u "%~dp0launcher.py" stop
echo.
pause