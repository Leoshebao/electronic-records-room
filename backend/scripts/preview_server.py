"""本地预览服务：托管前端 dist + 反向代理 /api 到后端，替代 Nginx 供试用。

用法（在 backend 目录，用项目 venv 的 python）：
    python scripts/preview_server.py --port 8080                      # 仅本机 HTTP
    python scripts/preview_server.py --port 8443 --ssl --host 0.0.0.0 # 局域网 HTTPS（证书取 deploy/certs）

说明：
- 静态资源取 frontend/dist，未知路径回退 index.html（SPA 前端路由）。
- 所有 /api/* 请求原样转发到 API_HOST:API_PORT（默认 127.0.0.1:8000），含方法、请求头、请求体与状态码。
- 仅用于试用/联调；正式部署仍用 deploy/nginx/nginx.local.conf。
"""
from __future__ import annotations

import argparse
import http.client
import mimetypes
import os
import ssl
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # output/erecords
DIST = ROOT / "frontend" / "dist"
CERTS = ROOT / "deploy" / "certs"

API_HOST = os.environ.get("PREVIEW_API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("PREVIEW_API_PORT", "8000"))

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("application/json", ".json")


class Handler(BaseHTTPRequestHandler):
    server_version = "erecords-preview/1.0"

    def log_message(self, fmt, *args):  # noqa: A003
        sys.stderr.write("[preview] " + (fmt % args) + "\n")

    # ---------- 内部工具 ----------
    def _cors_preflight(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "*"))
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,PATCH,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", self.headers.get("Access-Control-Request-Headers", "*"))
        self.end_headers()

    def _proxy(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in {"host", "connection"}}
        conn = http.client.HTTPConnection(API_HOST, API_PORT, timeout=300)
        try:
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            self.send_response(resp.status)
            hop_by_hop = {"connection", "keep-alive", "transfer-encoding", "upgrade", "content-length"}
            for k, v in resp.getheaders():
                if k.lower() not in hop_by_hop:
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
        except Exception as exc:  # noqa: BLE001
            msg = f'{{"code":"BAD_GATEWAY","message":"后端未启动或不可达：{exc}"}}'.encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
        finally:
            conn.close()

    def _static(self) -> None:
        path = self.path.split("?", 1)[0].split("#", 1)[0]
        if path in ("", "/"):
            path = "/index.html"
        target = (DIST / path.lstrip("/")).resolve()
        try:
            target.relative_to(DIST.resolve())
        except ValueError:
            self.send_error(403)
            return
        if not target.is_file():
            target = DIST / "index.html"  # SPA 回退
        if not target.is_file():
            self.send_error(404, "dist 未构建，请先执行 npm run build")
            return
        data = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in {"application/javascript", "application/json", "image/svg+xml"}:
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        name = target.name
        if name == "config.js" or name == "index.html":
            self.send_header("Cache-Control", "no-cache")
        elif "/assets/" in str(target):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    # ---------- 路由 ----------
    def do_GET(self):  # noqa: N802
        self._proxy() if self.path.startswith("/api/") else self._static()

    def do_HEAD(self):  # noqa: N802
        self._proxy() if self.path.startswith("/api/") else self._static()

    def do_POST(self):  # noqa: N802
        self._proxy() if self.path.startswith("/api/") else self.send_error(405)

    def do_PUT(self):  # noqa: N802
        self._proxy() if self.path.startswith("/api/") else self.send_error(405)

    def do_PATCH(self):  # noqa: N802
        self._proxy() if self.path.startswith("/api/") else self.send_error(405)

    def do_DELETE(self):  # noqa: N802
        self._proxy() if self.path.startswith("/api/") else self.send_error(405)

    def do_OPTIONS(self):  # noqa: N802
        self._cors_preflight()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--ssl", action="store_true", help="启用 HTTPS，证书取 deploy/certs/server.crt|server.key")
    args = ap.parse_args()

    if not (DIST / "index.html").is_file():
        print(f"前端未构建：{DIST} 缺少 index.html，请先 npm run build", file=sys.stderr)
        return 1

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    scheme = "http"
    if args.ssl:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(CERTS / "server.crt"), str(CERTS / "server.key"))
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"
    print(f"[preview] {scheme}://{args.host}:{args.port}  ->  dist={DIST}  api=http://{API_HOST}:{API_PORT}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("[preview] 已停止", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
