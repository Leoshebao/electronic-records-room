"""前端调用路径 × 后端路由定义 一致性校验（静态分析，无需启动服务）。
输出：前端调用清单、后端路由清单、缺失项（前端调用但后端未定义）、未使用项。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BE = os.path.join(ROOT, "backend", "app")
FE = os.path.join(ROOT, "frontend", "src")

# 后端 router -> (prefix, 挂载前缀)
MOUNT = {
    "health": ("", "/api"),
    "auth": ("/auth", "/api"),
    "users.router": ("", "/api"),
    "users.dept_router": ("/departments", "/api"),
    "rooms.router": ("/rooms", "/api"),
    "rooms.cat_router": ("/categories", "/api"),
    "documents": ("/documents", "/api"),
    "files": ("/files", "/api"),
    "ocr": ("/ocr", "/api"),
    "search": ("/search", "/api"),
    "borrow": ("/borrow", "/api"),
    "stats.audit_router": ("/audit", "/api"),
    "stats.router": ("/stats", "/api"),
    "backup": ("", "/api/backups"),
}

# 各文件内 router 变量 -> 挂载键
FILE_MOUNT = {
    "health.py": ["health"],
    "auth.py": ["auth"],
    "users.py": ["users.router", "users.dept_router"],
    "rooms.py": ["rooms.router", "rooms.cat_router"],
    "documents.py": ["documents"],
    "files.py": ["files"],
    "ocr.py": ["ocr"],
    "search.py": ["search"],
    "borrow.py": ["borrow"],
    "stats.py": ["stats.audit_router", "stats.router"],
    "backup.py": ["backup"],
}

VAR_TO_KEY = {}
for fname, keys in FILE_MOUNT.items():
    for k in keys:
        VAR_TO_KEY.setdefault(fname, {})[k.split(".")[-1] if "." in k else "router"] = k


def backend_routes():
    routes = set()
    rdir = os.path.join(BE, "api", "routes")
    for fname in sorted(os.listdir(rdir)):
        if not fname.endswith(".py") or fname == "__init__.py":
            continue
        src = io.open(os.path.join(rdir, fname), encoding="utf-8").read()
        var_map = VAR_TO_KEY.get(fname, {"router": "health"})
        for m in re.finditer(r"@(\w+)\.(get|post|patch|put|delete)\(\s*[\"']([^\"']*)[\"']", src):
            var, method, path = m.group(1), m.group(2).upper(), m.group(3)
            key = var_map.get(var)
            if not key:
                continue
            prefix, mount = MOUNT[key]
            full = (mount + prefix + path).rstrip("/") or mount
            routes.add((method, full))
    return routes


def norm(path, method):
    p = path.split("?")[0]
    p = re.sub(r"\$\{[^}]+\}", "{x}", p)
    p = re.sub(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", "{x}", p)
    p = re.sub(r"/\d+(?=/|$)", "/{x}", p)
    p = p.rstrip("/") or "/"
    return (method.upper(), p)


def seg_match(fe_path, be_path):
    """段级匹配：任一侧为通配 {x} 即视为该段相同。"""
    a = [s for s in fe_path.split("/") if s]
    b = [s for s in be_path.split("/") if s]
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x == "{x}" or y == "{x}":
            continue
        if x != y:
            return False
    return True


def frontend_calls():
    calls = []
    for dirpath, _dirs, files in os.walk(FE):
        for f in files:
            if not f.endswith((".ts", ".tsx")):
                continue
            fp = os.path.join(dirpath, f)
            src = io.open(fp, encoding="utf-8").read()
            for m in re.finditer(r"http\.(get|post|patch|put|delete)<[^>]*>\(\s*[`'\"]([^`'\"]+)[`'\"]", src):
                calls.append((m.group(1).upper(), m.group(2), f))
            for m in re.finditer(r"http\.(get|post|patch|put|delete)\(\s*[`'\"]([^`'\"]+)[`'\"]", src):
                calls.append((m.group(1).upper(), m.group(2), f))
            for m in re.finditer(r"(?:downloadFile|openBlobInNewTab)\(\s*[`'\"]([^`'\"]+)[`'\"]", src):
                calls.append(("GET", m.group(1), f))
    return calls


def main():
    routes = backend_routes()
    calls = frontend_calls()

    # 后端按 {x} 归一化
    be_norm = set()
    for method, p in routes:
        be_norm.add(norm(p, method))

    missing, ok = [], []
    for method, path, f in sorted(set(calls)):
        if not path.startswith("/"):
            continue
        key = norm("/api" + path if not path.startswith("/api") else path, method)
        # downloadFile 传的是相对 /api 的路径
        target = key if key[1].startswith("/api") else ("GET", "/api" + key[1])
        hit = target in be_norm or any(
            m == target[0] and seg_match(target[1], p) for m, p in be_norm
        )
        if hit:
            ok.append((method, path, f))
        else:
            missing.append((method, path, f, target))

    print("后端已定义路由数：", len(routes))
    print("前端调用点数：", len(set((m, p) for m, p, _ in calls)))
    print("匹配成功：", len(ok))
    print("未匹配：", len(missing))
    for m in missing:
        print("  [MISS]", m)

    used = set()
    for method, path, _f in calls:
        if not path.startswith("/"):
            continue
        key = norm("/api" + path if not path.startswith("/api") else path, method)
        used.add(key if key[1].startswith("/api") else ("GET", "/api" + key[1]))
    unused = sorted(r for r in routes if norm(r[1], r[0]) not in used)
    print("后端定义但前端未调用（正常，如 debug/内部接口）：", len(unused))
    for r in unused:
        print("  [UNUSED]", r)

    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
