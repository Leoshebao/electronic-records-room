@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM ===== 电子资料室系统 本地启动脚本（方案 B，无 Docker）=====
REM 前置条件：Python 3.11、PostgreSQL 16、Nginx、证书已生成（deploy\certs\gen-cert.ps1）

set "ROOT=%~dp0..\.."
cd /d "%ROOT%"

echo ==========================================
echo   电子资料室系统 启动中
echo ==========================================

REM ---- 1. 检查 .env ----
if not exist ".env" (
    echo [错误] 未找到 .env 文件
    echo        请复制 .env.example 为 .env 并修改配置
    pause
    exit /b 1
)

REM ---- 2. 检查 PostgreSQL 服务 ----
echo [1/6] 检查 PostgreSQL 服务...
sc query postgresql-x64-16 | find "RUNNING" >nul
if errorlevel 1 (
    echo        正在启动 PostgreSQL...
    net start postgresql-x64-16 >nul 2>&1
    if errorlevel 1 (
        echo [错误] PostgreSQL 服务启动失败，请确认已安装 PostgreSQL 16 且服务名为 postgresql-x64-16
        pause
        exit /b 1
    )
)
echo        OK

REM ---- 3. 检查虚拟环境 ----
echo [2/6] 检查 Python 虚拟环境...
if not exist "backend\.venv\Scripts\python.exe" (
    echo        首次运行，正在创建虚拟环境...
    python -m venv backend\.venv
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败，请确认已安装 Python 3.11 并加入 PATH
        pause
        exit /b 1
    )
    backend\.venv\Scripts\python.exe -m pip install --upgrade pip
    backend\.venv\Scripts\pip.exe install -r backend\requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络或离线包
        pause
        exit /b 1
    )
)
echo        OK

REM ---- 3.5 OCR 依赖（可选，首次安装；未装则扫描件解析标记 skipped）----
echo [2.5/6] 检查 OCR 依赖 (PaddleOCR)...
if exist "backend\.venv\Scripts\python.exe" (
    backend\.venv\Scripts\python.exe -c "import paddleocr" >nul 2>&1
    if errorlevel 1 (
        echo        未检测到 PaddleOCR，正在安装 OCR 附加依赖（约 400~600MB，需联网）...
        echo        如不需要扫描件识别，可按 Ctrl+C 跳过，系统其余功能不受影响。
        backend\.venv\Scripts\pip.exe install -r backend\requirements-ocr.txt
        if errorlevel 1 (
            echo [警告] OCR 依赖安装失败，扫描件将标记 skipped，可稍后手动执行：
            echo        backend\.venv\Scripts\pip.exe install -r backend\requirements-ocr.txt
        )
    )
)
echo        OK

REM ---- 4. 数据库迁移 ----
echo [3/6] 执行数据库迁移...
pushd backend
.venv\Scripts\alembic.exe upgrade head
if errorlevel 1 (
    echo [错误] 数据库迁移失败，请检查 .env 中的数据库配置
    popd
    pause
    exit /b 1
)
popd
echo        OK

REM ---- 5. 初始化管理员账号（幂等，已存在则跳过）----
echo [4/6] 检查管理员账号...
pushd backend
.venv\Scripts\python.exe scripts\check_empty_db.py
if errorlevel 1 (
    REM 库内已有资料室：只补部门与管理员，不注入示例数据
    .venv\Scripts\python.exe scripts\seed_admin.py
) else (
    REM 全新空库：额外初始化示例资料室与三级类目，开箱即可上传
    .venv\Scripts\python.exe scripts\seed_admin.py --with-samples
)
popd
echo        OK

REM ---- 6. 启动 API ----
echo [5/6] 启动后端 API (127.0.0.1:8000)...
start "erecords-api" /min cmd /c "cd /d %ROOT%\backend && .venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --proxy-headers"
timeout /t 3 >nul

REM ---- 7. 启动 Nginx ----
echo [6/6] 启动 Nginx (8443, HTTPS)...
tasklist /FI "IMAGENAME eq nginx.exe" 2>nul | find /I "nginx.exe" >nul
if errorlevel 1 (
    where nginx >nul 2>&1
    if errorlevel 1 (
        echo [警告] 未找到 nginx 命令，请将 Nginx 目录加入 PATH
        echo        或手动执行: nginx -p "%ROOT%\deploy\nginx" -c "%ROOT%\deploy\nginx\nginx.local.conf"
    ) else (
        nginx -p "%ROOT%\deploy\nginx" -c "%ROOT%\deploy\nginx\nginx.local.conf"
    )
) else (
    nginx -s reload -p "%ROOT%\deploy\nginx" -c "%ROOT%\deploy\nginx\nginx.local.conf" 2>nul
)
echo        OK

echo.
echo ==========================================
echo   启动完成
echo ==========================================
for /f "tokens=2 delims==" %%a in ('findstr /B "PUBLIC_BASE_URL" .env') do set "URL=%%a"
echo   访问地址: !URL!
echo   健康检查: !URL!/api/health
echo.
echo   停止服务请运行: deploy\scripts\stop.bat
echo ==========================================
pause
