# 电子资料室系统 — 部署说明书（P10）

适用环境：Windows 10/11 局域网，10~30 人，纯内网离线运行。
访问方式：`https://<服务器内网IP>:8443`，客户端首次需导入自签证书。

---

## 一、交付物清单

| 路径 | 说明 |
|------|------|
| `docker-compose.yml` | 方案 A：全容器编排（db + api + nginx） |
| `deploy/nginx/nginx.conf` | 方案 A 的 Nginx 配置（容器内路径、反代 `api:8000`） |
| `deploy/nginx/nginx.local.conf` | 方案 B 的 Nginx 配置（Windows 本机、反代 `127.0.0.1:8000`） |
| `deploy/certs/gen-cert.ps1` | 自签证书生成脚本（含 IP SAN，无 openssl 也能跑） |
| `deploy/certs/server.crt / server.key / server.pfx` | 已生成的证书 / Nginx 私钥 / 客户端导入包 |
| `deploy/scripts/start.bat / stop.bat` | 方案 B 一键启停 |
| `frontend/dist/` | 已构建的前端静态产物 |
| `frontend/public/config.js` | 运行时 API 地址配置（构建后拷到 `dist/`） |

---

## 二、方案 B：Windows 本机部署（推荐，10~30 人够用）

### 前置条件

1. Python 3.11（勾选 Add to PATH）
2. PostgreSQL 16，服务名 `postgresql-x64-16`，端口与 `.env` 一致
3. Nginx for Windows，解压目录加入 PATH（`where nginx` 能定位）
4. 已用当前内网 IP 生成证书（见第三节）

### 部署步骤

```powershell
# 1. 配置（首次）
copy .env.example .env
notepad .env      # 至少改 POSTGRES_PASSWORD、SECRET_KEY、PUBLIC_BASE_URL 中的 IP

# 2. 生成证书（IP 变更后必须重跑）
powershell -ExecutionPolicy Bypass -File deploy\certs\gen-cert.ps1 -ServerIP 192.168.1.100

# 3. 一键启动（自动完成：建虚拟环境 → 装依赖 → alembic 迁移 → 建管理员 → 起 API → 起 Nginx）
deploy\scripts\start.bat
```

启动脚本依次校验：`.env` 存在 → PostgreSQL 服务 RUNNING（未起则 `net start`）→ `backend\.venv` 存在（否则创建并装依赖）→ `alembic upgrade head` → `seed_admin.py`（幂等，**空库时自动加 `--with-samples`** 建一个「综合档案室」与三级示例类目）→ uvicorn 绑 `127.0.0.1:8000` → nginx 加载 `nginx.local.conf`。

### 关键约束（已写入配置，勿改）

| 项 | 值 | 原因 |
|----|----|------|
| 对外监听 | 仅 `8443 ssl` | 唯一对外端口 |
| 80 端口 | 301 跳 `https://$host:8443` | 兼容用户直接输 IP |
| API 绑定 | `127.0.0.1:8000` | 不得 `0.0.0.0`，否则绕过 TLS |
| TLS 版本 | `TLSv1.2 TLSv1.3` | 关闭 1.0/1.1 |
| HSTS | 不启用 | IP 直连场景会把浏览器锁死无法回退 |
| 上传上限 | `client_max_body_size 512m` | 需 ≥ `.env` 的 `MAX_UPLOAD_MB` |
| `config.js` | `Cache-Control: no-store` | 换 IP 后客户端立即生效 |

### 防火墙

```powershell
netsh advfirewall firewall add rule name="erecords-8443" dir=in action=allow protocol=TCP localport=8443
# 只允许内网网段（按实际网段调整）
netsh advfirewall firewall add rule name="erecords-8443-lan" dir=in action=allow protocol=TCP localport=8443 remoteip=192.168.1.0/24
```

如需限制访问来源，保留第二条并把 `remoteip` 收紧；`8000`、`5432` 一律不要放行。

### OCR 依赖（扫描件识别，必需能力）

PaddleOCR 未打进基础依赖（避免每次装依赖都拉 500MB），单独一个文件：

```powershell
cd backend
.venv\Scripts\pip.exe install -r requirements-ocr.txt
```

- CPU 版，无需显卡；首次识别时自动下载中文模型（约 20MB）缓存到 `%USERPROFILE%\.paddleocr`，之后纯离线可用。
- 完全离线环境：联网机器上 `pip download -r requirements-ocr.txt -d offline_wheels`，拷贝后 `pip install --no-index --find-links offline_wheels -r requirements-ocr.txt`。
- 验证：登录后进「系统自检」页，`ocr_engine.available` 应为 `true`；或直接 `curl -k https://127.0.0.1:8443/api/health/*`。
- 未安装时不阻断启动：有文本层的 PDF/Word/Excel 照常解析，扫描件解析状态为 `skipped`，文档详情会显示原因。
- `deploy\scripts\start.bat` 首次运行会检测并尝试自动安装。

---

## 三、自签证书与客户端分发

### 生成

```powershell
powershell -ExecutionPolicy Bypass -File deploy\certs\gen-cert.ps1 -ServerIP 192.168.1.100 -Days 365 -PfxPassword erecords
```

脚本优先用 `openssl`，无 openssl 时降级为 .NET `CertificateRequest` 直接输出 PEM，均不需管理员权限、不需联网。
生成物：`server.crt`（Nginx 用）、`server.key`（PKCS#8 明文私钥，Nginx 用）、`server.pfx`（客户端用，密码 `erecords`）。
SAN 固定包含：服务端内网 IP + `127.0.0.1` + `localhost`。

### 客户端分发（每台电脑一次）

1. 把 `server.pfx` 拷给客户端
2. 双击 → 安装证书 → 存储位置「本地计算机」→ 放入「受信任的根证书颁发机构」
3. 或命令行（管理员）：

```powershell
certutil -addstore -f Root server.pfx
```

4. 重启浏览器，访问 `https://192.168.1.100:8443`，地址栏应无证书告警

> 不导入也能访问（手动点「继续访问」），但每次告警；且部分浏览器对自签站点禁用部分功能。
> 服务器 IP 变更后必须重签并重新分发，否则 SAN 不匹配会直接报 `NET::ERR_CERT_COMMON_NAME_INVALID`。

---

## 四、方案 A：Docker 部署

```powershell
copy .env.example .env      # 修改配置
powershell -ExecutionPolicy Bypass -File deploy\certs\gen-cert.ps1 -ServerIP 192.168.1.100
docker compose up -d
docker compose ps           # api 应为 healthy
```

与方案 B 的差异仅两点：Nginx 容器内反代 `http://api:8000`；证书目录 `./deploy/certs` 只读挂载到 `/etc/nginx/certs`。
两套配置互不影响，方案 A 的 `nginx.conf` 使用 `/etc/nginx/mime.types`，**不能**直接拿到 Windows 本机的 Nginx 用。

---

## 五、已知坑（踩过的，务必看）

### 1. uvicorn 直接用 TLS 时 TLS1.2 握手必败

`uvicorn` 的 `--ssl-ciphers` 默认值是字符串 `TLSv1`。在 OpenSSL 3 下该别名对应的套件全被 `SECLEVEL=2` 禁用，导致**TLS1.2 客户端直接 EOF**（`UNEXPECTED_EOF_WHILE_READING`），而 TLS1.3 正常，极易误判为证书问题。

生产架构是 Nginx 终止 TLS、uvicorn 只跑明文，不受影响；但若做直连自测或临时改造，必须显式指定：

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 9443 `
  --ssl-certfile deploy\certs\server.crt --ssl-keyfile deploy\certs\server.key `
  --ssl-ciphers "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305"
```

`backend/scripts/verify_p10.py` 即按此参数启动并断言 TLS1.2/TLS1.3 均可握手。

### 2. Nginx 相对路径依赖 `-p` 前缀

`nginx.local.conf` 内 `../certs`、`../../frontend/dist` 都是相对路径，**必须**带前缀启动：

```
nginx -p "<项目根>\deploy\nginx" -c "<项目根>\deploy\nginx\nginx.local.conf"
```

漏掉 `-p` 会报 `open() "../certs/server.crt" failed`。

### 3. `nginx -t` 需要 logs / temp 目录存在

Nginx for Windows 首次运行前需 `deploy\nginx\logs`、`deploy\nginx\temp\*` 目录，否则 `nginx -t` 报 `CreateFile() "logs/error.log" failed`。

### 4. PowerShell 脚本中文乱码

含中文的 `.ps1` / `.bat` 必须存为 **UTF-8 with BOM**（bat 另加 `chcp 65001`），否则控制台输出乱码或解析失败。

### 5. 私钥必须是 PEM PKCS#8

`New-SelfSignedCertificate` 导出的私钥无法被 Nginx 直接加载。`gen-cert.ps1` 已改用 `CertificateRequest` + `ExportPkcs8PrivateKey`（缺失时回退 `CngKey` 导出），产出可直接使用的明文私钥。
若私钥带密码，Nginx 启动会卡在交互输入，**不要**给 `server.key` 加密。

### 6. 证书链与浏览器"继续访问"

自签证书若不导入客户端受信任根，`curl` / `httpx` 默认校验必失败——这是**预期行为**，不是部署错误。`verify_p10.py` 专门断言「未导入时校验必须失败」和「主机名不在 SAN 内必须被拒」，防止用人造宽松校验掩盖问题。

---

## 六、验收

```powershell
cd backend
.venv\Scripts\python.exe scripts\verify_p10.py
```

末行输出 `P10 验收：N/N 通过` 即为通过。覆盖五块共 51 项：

| 块 | 内容 |
|----|------|
| 部署配置 | 双方案 Nginx 关键指令、上传上限、反代头、`config.js` 禁缓存、80→8443 跳转、HSTS 未启用 |
| 证书 | SAN（IP/127.0.0.1/localhost）、剩余有效期、私钥 PKCS#8 且未加密、`pfx` 可导入 |
| TLS 真实握手 | uvicorn+TLS 实起，TLS1.3 / TLS1.2 协商、AEAD 前向保密套件、未受信必须失败、SAN 不匹配必须失败、明文打 TLS 端口必须失败、HTTPS `/api/health` 200 |
| 对外暴露面 | `API_HOST=127.0.0.1`、`PUBLIC_BASE_URL` 为 https:8443、启停脚本参数 |
| 前端 | `config.js` 定义 `__APP_CONFIG__`、加载顺序在业务脚本之前、引用 hash 化资源 |

本机未装 Nginx 时 `nginx -t` 一项记为 SKIP（不判失败），装好后会自动纳入。

一键串跑全部阶段：

```powershell
cd backend
.venv\Scripts\python.exe scripts\run_all_verify.py
```

---

## 七、排障速查

| 现象 | 定位 |
|------|------|
| 浏览器 `ERR_CONNECTION_REFUSED` | Nginx 未起；`tasklist \| findstr nginx`，看 `deploy\nginx\logs\error.log` |
| 页面能开但接口 502 | API 未起或端口不符；`netstat -ano \| findstr :8000`，看 uvicorn 窗口报错 |
| 接口 404 且路径正确 | 新路由未在 `app/main.py` `include_router`（本项目已发生过的坑） |
| 证书告警 | `server.pfx` 未导入受信任根，或服务器 IP 已变更未重签 |
| 上传 413 | `client_max_body_size` 小于 `MAX_UPLOAD_MB`，或 Nginx 未 reload |
| 换 IP 后前端还连旧地址 | `config.js` 被缓存；确认响应头 `Cache-Control: no-store` 并强刷 |
| 登录后立刻 401 | `SECRET_KEY` 被改而旧 token 未过期；或系统时间偏差过大 |
| OCR 一直 processing | Worker 未启用（`OCR_WORKER_ENABLED`）或模型未就绪，看 API 日志 |

日志位置：Nginx `deploy\nginx\logs\`；API 为 uvicorn 控制台窗口输出；OCR 任务失败原因查数据库 `ocr_tasks.error_message`。

---

## 八、备份与恢复

- 备份根目录 `.env` 的 `BACKUP_ROOT`（默认 `./backups`），保留 `BACKUP_KEEP_DAYS=30` 天
- 备份内容：数据库 dump + `storage/` 增量
- 恢复：停 API → 导入 dump → 回填 `storage/` → 起 API，存储文件名与数据库记录一一对应，不要改名
- 系统管理端「备份」页面可手动触发并下载，恢复需在服务器本地执行
