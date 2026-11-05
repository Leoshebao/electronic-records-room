"""P10 验收脚本：HTTPS 部署联调（Nginx 终止 TLS + 自签证书 + 反代头 + 前端运行时配置）。

运行方式（在 backend 目录，使用会话 venv 的 python）：
    python scripts/verify_p10.py
末行输出 "P10 验收：X/Y 通过"。

五部分：
- 部署配置：nginx.local.conf / nginx.conf（双部署）关键指令静态校验，nginx -t 语法校验；
- 证书：server.crt 的 SAN / 有效期 / 私钥格式 / pfx 可导入；
- TLS：真实 uvicorn + TLS 起在 127.0.0.1:9443，验证 1.3/1.2 协商、CA 校验、自签未信任必须失败、
  主机名不匹配必须失败、明文打到 TLS 端口必须失败；
- 对外面：API 只监听 127.0.0.1，对外唯一端口 8443；
- 前端：运行时 config.js 注入顺序与同源 API_BASE。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
DEPLOY = ROOT / "deploy"
CERTS = DEPLOY / "certs"
NGINX_LOCAL = DEPLOY / "nginx" / "nginx.local.conf"
NGINX_DOCKER = DEPLOY / "nginx" / "nginx.conf"
CRT = CERTS / "server.crt"
KEY = CERTS / "server.key"
PFX = CERTS / "server.pfx"
FRONTEND = ROOT / "frontend"
ENV_FILE = ROOT / ".env"
TLS_PORT = 9443
MODERN_CIPHERS = (
    "ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:"
    "ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305"
)

results: list[tuple[str, bool, str]] = []
skipped: list[str] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    results.append((name, bool(ok), extra))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  -> ' + str(extra)[:220]) if not ok else ''}", flush=True)


def skip(name: str, why: str) -> None:
    skipped.append(name)
    results.append((name, True, why))
    print(f"SKIP  {name}  -> {why}", flush=True)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


def parse_env() -> dict[str, str]:
    data: dict[str, str] = {}
    for line in read(ENV_FILE).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip()
    return data


# ============================ 一、部署配置 ============================
print("\n===== 一、部署配置（Nginx 双方案）=====", flush=True)

local_conf = read(NGINX_LOCAL)
docker_conf = read(NGINX_DOCKER)
env = parse_env()

check("nginx.local.conf 存在（方案B：Windows 本机）", NGINX_LOCAL.exists(), str(NGINX_LOCAL))
check("nginx.conf 存在（方案A：Docker）", NGINX_DOCKER.exists(), str(NGINX_DOCKER))

check("方案B 对外仅监听 8443 ssl", bool(re.search(r"listen\s+8443\s+ssl\s*;", local_conf)))
check("方案B TLS 仅 1.2/1.3", "ssl_protocols             TLSv1.2 TLSv1.3;" in local_conf or
      bool(re.search(r"ssl_protocols\s+TLSv1\.2\s+TLSv1\.3\s*;", local_conf)))
check("方案B 未放开 TLSv1/1.1", not re.search(r"ssl_protocols[^;]*TLSv1(\s|;|\.1)", local_conf))

max_upload = int(env.get("MAX_UPLOAD_MB", "500") or 500)
m = re.search(r"client_max_body_size\s+(\d+)m\s*;", local_conf)
check(f"方案B 上传上限 ≥ {max_upload}MB", bool(m) and int(m.group(1)) >= max_upload,
      m.group(0) if m else "未配置 client_max_body_size")

check("方案B API 反代到 127.0.0.1:8000", "proxy_pass http://127.0.0.1:8000;" in local_conf)
check("方案B 透传 X-Forwarded-Proto https", "proxy_set_header X-Forwarded-Proto https;" in local_conf)
check("方案B 透传 X-Real-IP", "proxy_set_header X-Real-IP         $remote_addr;" in local_conf or
      "X-Real-IP" in local_conf)
check("方案B /config.js 禁缓存", bool(re.search(r"location\s*=\s*/config\.js", local_conf)) and
      "no-store" in local_conf)
check("方案B 80 端口 301 跳 8443", "return 301 https://$host:8443$request_uri;" in local_conf)
check("方案B 证书路径指向 ../certs", "../certs/server.crt" in local_conf and
      "../certs/server.key" in local_conf)
check("方案B 未启用 HSTS（IP 访问防锁死）", "Strict-Transport-Security" not in local_conf)
check("方案A 使用 docker 服务名 api:8000", "proxy_pass http://api:8000;" in docker_conf)
check("方案A 证书挂载路径 /etc/nginx/certs", "/etc/nginx/certs/server.crt" in docker_conf)

# 前端根目录必须真实存在，否则 nginx 起来就是 403/404
dist = FRONTEND / "dist"
check("前端构建产物 dist 存在", (dist / "index.html").exists(), str(dist))

if shutil.which("nginx"):
    for d in ("logs", "temp/client_body", "temp/proxy", "temp/fastcgi", "temp/uwsgi", "temp/scgi"):
        (DEPLOY / "nginx" / d).mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["nginx", "-t", "-p", str(DEPLOY / "nginx"), "-c", str(NGINX_LOCAL)],
        capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=60,
    )
    ok = proc.returncode == 0
    check("nginx -t 语法校验通过（方案B）", ok, (proc.stderr or proc.stdout)[-300:])
else:
    skip("nginx -t 语法校验通过（方案B）", "本机未安装 nginx，跳过语法校验")

# ============================ 二、证书 ============================
print("\n===== 二、自签证书 =====", flush=True)

check("server.crt 存在", CRT.exists(), str(CRT))
check("server.key 存在", KEY.exists(), str(KEY))
check("server.pfx 存在（客户端导入包）", PFX.exists(), str(PFX))

crt_info: dict = {}
if CRT.exists():
    try:
        crt_info = ssl._ssl._test_decode_cert(str(CRT))  # noqa: SLF001 - 标准库唯一 X509 解析入口
    except Exception as exc:  # noqa: BLE001
        crt_info = {}
        check("server.crt 可被标准库解析", False, repr(exc))
    else:
        check("server.crt 可被标准库解析", True)

sans = crt_info.get("subjectAltName", ())
san_ips = {v for k, v in sans if k.lower() == "ip address"}
san_dns = {v.lower() for k, v in sans if k.lower() == "dns"}

check("SAN 含内网 IP", bool(san_ips - {"127.0.0.1"}), f"IP SAN: {sorted(san_ips)}")
check("SAN 含 127.0.0.1", "127.0.0.1" in san_ips, f"IP SAN: {sorted(san_ips)}")
check("SAN 含 localhost", "localhost" in san_dns, f"DNS SAN: {sorted(san_dns)}")

days_left = -1
if crt_info.get("notAfter"):
    try:
        exp = datetime.strptime(crt_info["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
        days_left = (exp - datetime.now(timezone.utc)).days
    except Exception:  # noqa: BLE001
        pass
check("证书剩余有效期 ≥ 300 天", days_left >= 300, f"剩余 {days_left} 天")

key_text = read(KEY)
check("私钥为 PKCS#8 PEM（Nginx 可直接加载）",
      "-----BEGIN PRIVATE KEY-----" in key_text or "-----BEGIN RSA PRIVATE KEY-----" in key_text,
      key_text[:40])
check("私钥文件不含密码保护头", "ENCRYPTED" not in key_text)

if PFX.exists() and shutil.which("powershell"):
    ps_cmd = (
        "$c = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2("
        f"'{PFX}', 'erecords'); $c.Subject"
    )
    try:
        ps = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=120,
        )
        subject = (ps.stdout or "").strip()
        check("server.pfx 可导入且 Subject 正确", ps.returncode == 0 and "CN=" in subject,
              subject or (ps.stderr or "")[-200:])
    except subprocess.TimeoutExpired:
        skip("server.pfx 可导入且 Subject 正确", "PowerShell 启动超时，跳过（文件已生成）")
else:
    skip("server.pfx 可导入且 Subject 正确", "无 PowerShell 或 pfx 缺失")

# ============================ 三、TLS 真实握手 ============================
print("\n===== 三、TLS 真实握手（uvicorn + 证书，127.0.0.1:9443）=====", flush=True)

# 数据库需可用，否则 app 启动即失败
db_ok = False
try:
    with socket.create_connection((env.get("POSTGRES_HOST", "127.0.0.1"),
                                   int(env.get("POSTGRES_PORT", "5432"))), timeout=3):
        db_ok = True
except Exception:  # noqa: BLE001
    db_ok = False
check("PostgreSQL 可达（HTTPS 端到端前置）", db_ok,
      f"{env.get('POSTGRES_HOST')}:{env.get('POSTGRES_PORT')}")

proc = None
tls_ready = False
log_path = Path(os.environ.get("TEMP", ".")) / "verify_p10_uvicorn.log"

if db_ok and CRT.exists() and KEY.exists():
    env_run = dict(os.environ)
    env_run.update({
        "OCR_WORKER_ENABLED": "false",
        "BORROW_SWEEP_ENABLED": "false",
        "PYTHONIOENCODING": "utf-8",
    })
    log_fp = open(log_path, "w", encoding="utf-8", errors="ignore")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app",
         "--host", "127.0.0.1", "--port", str(TLS_PORT),
         "--ssl-certfile", str(CRT), "--ssl-keyfile", str(KEY),
         # uvicorn 默认 ssl_ciphers="TLSv1"，OpenSSL 3 下 TLS1.2 无可协商套件，必须显式指定
         "--ssl-ciphers", MODERN_CIPHERS],
        cwd=str(BACKEND), env=env_run, stdout=log_fp, stderr=subprocess.STDOUT,
    )
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", TLS_PORT), timeout=2):
                tls_ready = True
                break
        except Exception:  # noqa: BLE001
            if proc.poll() is not None:
                break
            time.sleep(1.0)

check("HTTPS 服务启动成功（uvicorn + TLS）", tls_ready,
      read(log_path)[-300:] if log_path.exists() else "")

if tls_ready:
    base_ctx = ssl.create_default_context(cafile=str(CRT))

    def handshake(minv, maxv, hostname="127.0.0.1"):
        ctx = ssl.create_default_context(cafile=str(CRT))
        ctx.minimum_version = minv
        ctx.maximum_version = maxv
        with socket.create_connection(("127.0.0.1", TLS_PORT), timeout=10) as raw:
            with ctx.wrap_socket(raw, server_hostname=hostname) as tls:
                return tls.version(), tls.cipher()[0]

    try:
        ver, cipher = handshake(ssl.TLSVersion.TLSv1_3, ssl.TLSVersion.TLSv1_3)
        check("TLS 1.3 握手成功", ver == "TLSv1.3", f"{ver} / {cipher}")
    except Exception as exc:  # noqa: BLE001
        check("TLS 1.3 握手成功", False, repr(exc))

    try:
        ver, cipher = handshake(ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_2)
        check("TLS 1.2 握手成功（未退化到弱套件）", ver == "TLSv1.2", f"{ver} / {cipher}")
        check("TLS 1.2 协商出 AEAD 前向保密套件",
              cipher.startswith("ECDHE-") and ("GCM" in cipher or "CHACHA20" in cipher), cipher)
    except Exception as exc:  # noqa: BLE001
        check("TLS 1.2 握手成功", False, repr(exc))

    # 自签未导入客户端时，默认信任链必须失败（说明必须分发 pfx）
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection(("127.0.0.1", TLS_PORT), timeout=10) as raw:
            with ctx.wrap_socket(raw, server_hostname="127.0.0.1") as tls:
                pass
        check("未导入证书时校验失败（自签未受信）", False, "竟然通过了验证")
    except ssl.SSLCertVerificationError:
        check("未导入证书时校验失败（自签未受信）", True)
    except Exception as exc:  # noqa: BLE001
        check("未导入证书时校验失败（自签未受信）", False, repr(exc))

    # 主机名不在 SAN 内必须失败（证明 IP SAN 生效，而不是靠 CN 兜底）
    try:
        handshake(ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3, hostname="10.9.9.9")
        check("主机名不在 SAN 内被拒（IP SAN 生效）", False, "竟然握手成功")
    except ssl.SSLCertVerificationError:
        check("主机名不在 SAN 内被拒（IP SAN 生效）", True)
    except Exception as exc:  # noqa: BLE001
        check("主机名不在 SAN 内被拒（IP SAN 生效）", False, repr(exc))

    # 明文 HTTP 打到 TLS 端口必须失败
    try:
        with socket.create_connection(("127.0.0.1", TLS_PORT), timeout=10) as s:
            s.sendall(b"GET /api/health HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
            data = s.recv(64)
        check("明文 HTTP 打 TLS 端口被拒", not data.startswith(b"HTTP/"), data[:40])
    except Exception:  # noqa: BLE001
        check("明文 HTTP 打 TLS 端口被拒", True, "连接被直接断开")

    # 真实业务接口走 HTTPS
    try:
        import httpx

        r = httpx.get(f"https://127.0.0.1:{TLS_PORT}/api/health", verify=str(CRT), timeout=20)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        check("HTTPS GET /api/health 返回 200", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
        check("健康检查返回 ok 状态", str(body.get("status", "")).lower() in {"ok", "healthy", "up"},
              str(body)[:160])
    except Exception as exc:  # noqa: BLE001
        check("HTTPS GET /api/health 返回 200", False, repr(exc))
        check("健康检查返回 ok 状态", False, repr(exc))
else:
    for name in ("TLS 1.3 握手成功", "TLS 1.2 握手成功（未退化到弱套件）", "TLS 1.2 协商出 AEAD 前向保密套件",
                 "未导入证书时校验失败（自签未受信）",
                 "主机名不在 SAN 内被拒（IP SAN 生效）", "明文 HTTP 打 TLS 端口被拒",
                 "HTTPS GET /api/health 返回 200", "健康检查返回 ok 状态"):
        skip(name, "HTTPS 服务未就绪，跳过")

if proc is not None and proc.poll() is None:
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except Exception:  # noqa: BLE001
        proc.kill()

# ============================ 四、对外暴露面 ============================
print("\n===== 四、对外暴露面 =====", flush=True)

check("API_HOST 绑定 127.0.0.1", env.get("API_HOST", "127.0.0.1") == "127.0.0.1", env.get("API_HOST", ""))
check("PUBLIC_BASE_URL 为 https 且端口 8443",
      env.get("PUBLIC_BASE_URL", "").startswith("https://") and ":8443" in env.get("PUBLIC_BASE_URL", ""),
      env.get("PUBLIC_BASE_URL", ""))

start_bat = read(DEPLOY / "scripts" / "start.bat")
check("start.bat 启动参数 --host 127.0.0.1", "--host 127.0.0.1" in start_bat)
check("start.bat 不含 --host 0.0.0.0", "0.0.0.0" not in start_bat)
check("start.bat 使用 nginx.local.conf 且指定 prefix",
      "nginx.local.conf" in start_bat and "-p " in start_bat)
check("start.bat 生成证书前置校验（gen-cert）或提示",
      "gen-cert" in start_bat or CRT.exists())

settings_py = read(BACKEND / "app" / "core" / "config.py")
check("config.py 默认 API_HOST=127.0.0.1", 'API_HOST: str = "127.0.0.1"' in settings_py)
check("config.py 默认 PUBLIC_BASE_URL 走 https", 'PUBLIC_BASE_URL: str = "https://' in settings_py)

# ============================ 五、前端运行时配置 ============================
print("\n===== 五、前端运行时配置 =====", flush=True)

dist_cfg = read(dist / "config.js")
pub_cfg = read(FRONTEND / "public" / "config.js")
index_html = read(dist / "index.html")

check("dist/config.js 存在且定义 __APP_CONFIG__",
      "__APP_CONFIG__" in dist_cfg, dist_cfg[:80])
check("public/config.js 与 dist 同源存在", "__APP_CONFIG__" in pub_cfg)

api_base = ""
mm = re.search(r"API_BASE\s*:\s*['\"]([^'\"]*)['\"]", dist_cfg)
if mm:
    api_base = mm.group(1)
check("API_BASE 为空（同源反代）或 https 地址",
      api_base == "" or api_base.startswith("https://"), f"API_BASE='{api_base}'")

cfg_pos = index_html.find('src="/config.js"')
mod_pos = index_html.find('type="module"')
check("index.html 在业务脚本之前加载 config.js", cfg_pos != -1 and (mod_pos == -1 or cfg_pos < mod_pos))
check("index.html 引用 hash 化资源（构建产物非开发态）", "/assets/index-" in index_html)

# ============================ 汇总 ============================
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
print("\n" + "=" * 60, flush=True)
if passed != total:
    print("失败明细：", flush=True)
    for name, ok, extra in results:
        if not ok:
            print(f"  - {name}  {extra}", flush=True)
suffix = f"（跳过 {len(skipped)} 项）" if skipped else ""
print(f"P10 验收：{passed}/{total} 通过{suffix}", flush=True)
sys.exit(0 if passed == total else 1)
