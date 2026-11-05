# -*- coding: utf-8 -*-
"""电子资料室系统 便携版启动器。

用法:
    python launcher.py start   启动数据库 / 后端 / 前端页面
    python launcher.py stop    停止全部服务
    python launcher.py status  查看运行状态
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
PY = BASE / "runtime" / "python" / "python.exe"
PGBIN = BASE / "runtime" / "pg" / "bin"
PGDATA = BASE / "pgdata"
LOGS = BASE / "logs"
BACKEND = BASE / "backend"

DETACHED = 0x00000008
NEW_GROUP = 0x00000200
FLAGS = DETACHED | NEW_GROUP


def load_env() -> dict:
    cfg = {}
    env_file = BASE / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) != 0


def http_ok(url: str, timeout=2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


def run(cmd, log_name=None, cwd=None, timeout=180):
    """同步执行（用于 initdb / psql 等短命命令），输出落日志。"""
    cwd = str(cwd) if cwd else None
    if log_name:
        LOGS.mkdir(exist_ok=True)
        with open(LOGS / log_name, "a", encoding="utf-8", errors="ignore") as out:
            return subprocess.run([str(c) for c in cmd], cwd=cwd, stdin=subprocess.DEVNULL,
                                  stdout=out, stderr=subprocess.STDOUT, timeout=timeout)
    return subprocess.run([str(c) for c in cmd], cwd=cwd, capture_output=True,
                          text=True, encoding="mbcs", errors="ignore", timeout=timeout)


def spawn(cmd, log_name, cwd=None):
    LOGS.mkdir(exist_ok=True)
    f = open(LOGS / log_name, "a", encoding="utf-8", errors="ignore")
    p = subprocess.Popen([str(c) for c in cmd], cwd=str(cwd) if cwd else None,
                         stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT,
                         creationflags=FLAGS, close_fds=True)
    return p, f


def wait_port(port, seconds=90, label=""):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if not port_free(port):
            return True
        time.sleep(0.5)
    print(f"  [超时] {label} 端口 {port} 未就绪")
    return False


def wait_http(url, seconds=120, label=""):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if http_ok(url):
            return True
        time.sleep(1)
    print(f"  [超时] {label} 未响应: {url}")
    return False


def pg_ready(port) -> bool:
    return not port_free(port)


def start_pg(port):
    if pg_ready(port):
        print(f"  [1/3] 数据库已在运行 (127.0.0.1:{port})")
        return True

    first = not (PGDATA / "PG_VERSION").exists()
    if first:
        print("  [1/3] 首次运行：初始化数据库（约 1 分钟，请稍候）...")
        LOGS.mkdir(exist_ok=True)
        pw = LOGS / "pgpw.tmp"
        pw.write_text("DevLocal@2026\n", encoding="ascii")
        r = run([PGBIN / "initdb.exe", "-D", PGDATA, "-U", "postgres", f"--pwfile={pw}",
                 "-E", "UTF8", "--locale=C", "-A", "trust"], log_name="initdb.log", timeout=600)
        if r.returncode != 0:
            print("  [失败] initdb 出错，详见 logs\\initdb.log")
            return False
        print("        数据库集群初始化完成")
    else:
        print(f"  [1/3] 启动数据库 (端口 {port}) ...")

    # 通过 pg_ctl 启动：Windows 上 pg_ctl 会用受限令牌拉起 postmaster，
    # 避免"以管理员身份运行 postgres 被拒绝"的问题；cmd 以脱离控制台方式启动，
    # 关闭启动窗口不影响数据库进程。
    LOGS.mkdir(exist_ok=True)
    logf = open(LOGS / "pgctl.log", "a", encoding="utf-8", errors="ignore")
    subprocess.Popen(
        [str(PGBIN / "pg_ctl.exe"), "-D", str(PGDATA), "-l", str(LOGS / "postgres.log"),
         "-o", f"-p {port} -c listen_addresses=127.0.0.1", "-w", "-t", "90", "start"],
        cwd=str(BASE), stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
        creationflags=FLAGS, close_fds=True)
    logf.close()

    if not wait_port(port, 150, "数据库"):
        print("  [失败] 数据库启动失败，详见 logs\\postgres.log 与 logs\\pgctl.log")
        return False

    if first:
        run([PGBIN / "createdb.exe", "-h", "127.0.0.1", "-p", port, "-U", "postgres", "erecords"],
            log_name="initdb.log")
        dump = BASE / "data" / "erecords_data.sql"
        if dump.is_file():
            print("        正在导入初始业务数据 ...")
            run([PGBIN / "psql.exe", "-h", "127.0.0.1", "-p", port, "-U", "postgres",
                 "-d", "erecords", "-q", "-f", dump], log_name="restore.log", timeout=600)
        else:
            run([PY, "-m", "alembic", "upgrade", "head"], log_name="initdb.log", cwd=BACKEND)
            run([PY, "scripts/seed_admin.py"], log_name="initdb.log", cwd=BACKEND)
        print("        数据库初始化完成")
    print(f"        数据库就绪  127.0.0.1:{port}")
    return True


def start_api(port):
    if not port_free(port):
        print(f"  [2/3] 后端已在运行 (http://127.0.0.1:{port})")
        return True
    print(f"  [2/3] 启动后端服务 (端口 {port}) ...")
    env = os.environ.copy()
    env["PATH"] = f"{PGBIN}{os.pathsep}{env.get('PATH', '')}"
    LOGS.mkdir(exist_ok=True)
    logf = open(LOGS / "api.log", "a", encoding="utf-8", errors="ignore")
    proc = subprocess.Popen(
        [str(PY), "-u", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(BACKEND), stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
        creationflags=FLAGS, close_fds=True, env=env)
    (LOGS / "api.pid").write_text(str(proc.pid), encoding="utf-8")
    logf.close()
    if not wait_http(f"http://127.0.0.1:{port}/api/health", 150, "后端"):
        print("  [失败] 后端未就绪，详见 logs\\api.log")
        return False
    print(f"        后端就绪  http://127.0.0.1:{port}")
    return True


def start_web(port, api_port):
    if not port_free(port):
        print(f"  [3/3] 前端页面已在运行 (http://127.0.0.1:{port})")
        return True
    print(f"  [3/3] 启动前端页面 (端口 {port}) ...")
    LOGS.mkdir(exist_ok=True)
    logf = open(LOGS / "web.log", "a", encoding="utf-8", errors="ignore")
    env = os.environ.copy()
    env["PREVIEW_API_PORT"] = str(api_port)
    proc = subprocess.Popen(
        [str(PY), "-u", "scripts/preview_server.py", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(BACKEND), stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
        creationflags=FLAGS, close_fds=True, env=env)
    (LOGS / "web.pid").write_text(str(proc.pid), encoding="utf-8")
    logf.close()
    if not wait_http(f"http://127.0.0.1:{port}/", 60, "前端页面"):
        print("  [失败] 前端页面未就绪，详见 logs\\web.log")
        return False
    print(f"        页面就绪  http://127.0.0.1:{port}")
    return True


def cmd_start():
    cfg = load_env()
    pg_port = int(cfg.get("POSTGRES_PORT", 4854))
    api_port = int(cfg.get("API_PORT", 8000))
    web_port = int(cfg.get("PORTABLE_WEB_PORT", 8080))

    print("=" * 52)
    print("   电子资料室系统  便携版")
    print(f"   访问地址: http://127.0.0.1:{web_port}")
    print("=" * 52)

    if not PY.is_file():
        print("[错误] 运行环境缺失: runtime\\python\\python.exe")
        return 1
    for sub in ("storage", "backups", "logs"):
        (BASE / sub).mkdir(exist_ok=True)
    if not start_pg(pg_port):
        return 1
    if not start_api(api_port):
        return 1
    if not start_web(web_port, api_port):
        return 1

    print()
    print("=" * 52)
    print(f"  启动完成：http://127.0.0.1:{web_port}")
    print("  默认管理员：admin / Admin@12345#V")
    print("  停止服务：运行 stop.bat")
    print("=" * 52)
    try:
        os.startfile(f"http://127.0.0.1:{web_port}")
    except Exception:
        pass
    return 0


def kill_pid(pid):
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True,
                   creationflags=0x08000000)


def read_pid(name):
    p = LOGS / name
    if p.is_file():
        try:
            return int(p.read_text(encoding="utf-8").strip())
        except Exception:
            return None
    return None


def cmd_stop():
    cfg = load_env()
    pg_port = int(cfg.get("POSTGRES_PORT", 4854))
    print("正在停止电子资料室系统 ...")

    for name in ("web.pid", "api.pid"):
        pid = read_pid(name)
        if pid:
            kill_pid(pid)
            print(f"  已停止 {name.split('.')[0]} (PID {pid})")

    if (PGDATA / "PG_VERSION").exists():
        r = run([PGBIN / "pg_ctl.exe", "-D", PGDATA, "-m", "fast", "-w", "-t", "60", "stop"],
                log_name="pgctl.log")
        print("  数据库已停止" if r.returncode == 0 else "  数据库停止返回非零（可能本就未运行）")

    tmp = LOGS / "pgpw.tmp"
    print("完成。")
    return 0


def cmd_status():
    cfg = load_env()
    pg_port = int(cfg.get("POSTGRES_PORT", 4854))
    api_port = int(cfg.get("API_PORT", 8000))
    web_port = int(cfg.get("PORTABLE_WEB_PORT", 8080))
    checks = [("数据库", pg_port), ("后端 API", api_port), ("前端页面", web_port)]
    for label, port in checks:
        print(f"  {label:<8} 端口 {port}  " + ("运行中" if not port_free(port) else "未运行"))
    return 0


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "start"
    LOGS.mkdir(exist_ok=True)
    sys.exit({"start": cmd_start, "stop": cmd_stop, "status": cmd_status}.get(action, cmd_start)())
