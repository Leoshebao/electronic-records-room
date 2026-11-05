@echo off
chcp 65001 >nul
setlocal

set "ROOT=%~dp0..\.."
cd /d "%ROOT%"

echo ==========================================
echo   电子资料室系统 停止中
echo ==========================================

echo [1/3] 停止 Nginx...
where nginx >nul 2>&1
if errorlevel 1 (
    echo        未找到 nginx 命令，尝试结束后台进程
    taskkill /F /IM nginx.exe >nul 2>&1
) else (
    nginx -s quit -p "%ROOT%\deploy\nginx" -c "%ROOT%\deploy\nginx\nginx.local.conf" 2>nul
    if errorlevel 1 taskkill /F /IM nginx.exe >nul 2>&1
)
echo        OK

echo [2/3] 停止后端 API...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%p >nul 2>&1
)
echo        OK

echo [3/3] 停止 OCR Worker...
for /f "tokens=5" %%p in ('wmic process where "commandline like '%%app.worker%%'" get processid /value ^| find "="') do (
    set "PID=%%p"
    taskkill /F /PID !PID! >nul 2>&1
)
echo        OK

echo.
echo 已停止。数据库服务保持运行（如需停止: net stop postgresql-x64-16）
echo ==========================================
pause
