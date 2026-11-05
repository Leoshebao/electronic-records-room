# 本地试用启动脚本（无 Nginx 环境下的替代方案）
# 用途：拉起后端 uvicorn(127.0.0.1:8000) + 预览服务(127.0.0.1:8080，托管 dist 并反代 /api)
# 用法：在 PowerShell 中执行  powershell -ExecutionPolicy Bypass -File deploy\scripts\start-preview.ps1
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # output\erecords
$backend = Join-Path $root "backend"
$dist = Join-Path $root "frontend\dist"
$logDir = Join-Path $env:TEMP "erecords-preview"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# 定位可用 Python：优先项目 venv，其次 PATH 中的 python
$py = $null
foreach ($c in @((Join-Path $backend ".venv\Scripts\python.exe"), (Join-Path $env:TEMP "venv\Scripts\python.exe"))) {
    if (Test-Path $c) { $py = $c; break }
}
if (-not $py) { $py = (Get-Command python -ErrorAction SilentlyContinue).Source }
if (-not $py) { throw "未找到 Python，请先安装或确认 venv 路径" }

function Test-Port([int]$port) {
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
}

if (-not (Test-Path (Join-Path $dist "index.html"))) {
    Write-Host "[!] 前端未构建，正在执行 npm run build ..." -ForegroundColor Yellow
    Push-Location (Join-Path $root "frontend"); npm run build; Pop-Location
}

if (-not (Test-Port 8000)) {
    Write-Host "[1/2] 启动后端 API 127.0.0.1:8000 ..."
    Start-Process -FilePath $py -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8000","--proxy-headers" `
        -WorkingDirectory $backend -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "api.out.log") -RedirectStandardError (Join-Path $logDir "api.err.log")
    Start-Sleep -Seconds 5
} else { Write-Host "[1/2] 后端已在运行，跳过" }

if (-not (Test-Port 8080)) {
    Write-Host "[2/2] 启动预览服务 127.0.0.1:8080 ..."
    Start-Process -FilePath $py -ArgumentList "-u","scripts\preview_server.py","--port","8080" `
        -WorkingDirectory $backend -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logDir "preview.out.log") -RedirectStandardError (Join-Path $logDir "preview.err.log")
    Start-Sleep -Seconds 4
} else { Write-Host "[2/2] 预览服务已在运行，跳过" }

try {
    $h = Invoke-RestMethod "http://127.0.0.1:8080/api/health" -TimeoutSec 10
    Write-Host "`n[OK] 系统就绪：http://127.0.0.1:8080" -ForegroundColor Green
    Write-Host "     账号 admin  密码 Admin@12345#V"
    Write-Host "     日志目录 $logDir"
} catch {
    Write-Host "`n[!] 服务未就绪，请查看日志：$logDir" -ForegroundColor Red
    Write-Host $_.Exception.Message
}
