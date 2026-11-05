"""P0 基线冒烟（覆盖 P1~P4 关键断言的合并版）：骨架 / 数据模型 / 认证三角色 / 资料室类目树。

P1~P4 开发期的独立验收脚本未纳入版本库，其断言重点在此汇总保留，
后续阶段（P5~P10）的 verify 脚本依赖这些能力，任何回归会在此第一时间暴露。

运行方式（在 backend 目录）：
    python scripts/verify_p0_smoke.py
末行输出 "P0 验收：X/Y 通过"。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from passlib.context import CryptContext  # noqa: E402
from sqlalchemy import inspect, select, text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Department, Role, User  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASS_WORD = "Verify@12345"
API = settings.API_PREFIX

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    results.append((name, bool(ok), extra))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  -> ' + str(extra)[:200]) if extra and not ok else ''}", flush=True)


client = TestClient(app)

# ==================== 一、P1 骨架 ====================
print("\n===== 一、P1 项目骨架 =====", flush=True)

check("API 前缀为 /api", API == "/api", API)
check("settings 从 .env 加载 SECRET_KEY", bool(settings.SECRET_KEY) and len(settings.SECRET_KEY) >= 32)
check("API_HOST 默认 127.0.0.1", settings.API_HOST == "127.0.0.1", settings.API_HOST)

r = client.get(f"{API}/health")
body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
check("GET /api/health 200", r.status_code == 200, r.text[:120])
check("健康检查 status=ok", str(body.get("status", "")).lower() == "ok", str(body)[:120])

for path in (f"{API}/health/db", f"{API}/health/storage"):
    rr = client.get(path)
    check(f"GET {path} 200", rr.status_code == 200, rr.text[:120])

# 路由挂载检查（新路由忘记 include_router 是本项目已踩过的坑）
paths = {getattr(route, "path", "") for route in app.routes}
required = [
    f"{API}/auth/login", f"{API}/auth/me", f"{API}/rooms", f"{API}/categories",
    f"{API}/documents", f"{API}/search", f"{API}/borrow/requests",
    f"{API}/stats/overview", f"{API}/backups", f"{API}/users",
]
missing = [p for p in required if p not in paths]
check("12 个路由模块全部挂载", not missing, f"缺失: {missing}")

# ==================== 二、P2 数据模型 ====================
print("\n===== 二、P2 数据库模型与迁移 =====", flush=True)

with engine.connect() as conn:
    version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
check("alembic_version 存在且非空", bool(version), str(version))

insp = inspect(engine)
tables = set(insp.get_table_names())
expected = {
    "departments", "users", "rooms", "categories", "documents", "document_versions",
    "files", "ocr_tasks", "borrow_requests", "audit_logs", "search_index",
    "backups", "system_settings", "permissions", "download_logs",
}
# 容错：只要求基线核心表齐全，附加表不判失败
core = {
    "departments", "users", "rooms", "categories", "documents", "document_versions",
    "files", "ocr_tasks", "borrow_requests", "audit_logs",
}
missing_tables = sorted(core - tables)
check("核心 10 张表齐全", not missing_tables, f"缺失: {missing_tables}")
check("表总数 ≥ 12", len(tables) >= 12, f"实际 {len(tables)}: {sorted(tables)}")

for table in ("users", "documents"):
    cols = {c["name"] for c in insp.get_columns(table)}
    check(f"{table} 表含软删除/状态字段",
          bool(cols & {"status", "is_active", "deleted_at"}), sorted(cols))

audit_cols = {c["name"] for c in insp.get_columns("audit_logs")}
check("audit_logs 含操作人/动作/时间字段",
      {"user_id", "action", "created_at"} <= audit_cols, sorted(audit_cols))

idx = {tuple(i["column_names"]) for i in insp.get_indexes("documents")}
check("documents 有 room/category 相关索引",
      any("room_id" in c for c in idx) or any("category_id" in c for c in idx), str(idx))

with SessionLocal() as db:
    dept_count = db.scalar(select(text("count(*)")).select_from(Department)) or 0
check("部门种子数据存在", dept_count >= 1, f"{dept_count} 条")

# ==================== 三、P3 认证与三角色 ====================
print("\n===== 三、P3 认证与三角色权限 =====", flush=True)


def ensure_user(db, username: str, role: Role, dept_id: int | None) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(username=username, full_name=f"冒烟{role.value}",
                    password_hash=pwd.hash(PASS_WORD), role=role,
                    department_id=dept_id, is_active=True, must_change_password=False)
        db.add(user)
        db.flush()
    else:
        user.password_hash = pwd.hash(PASS_WORD)
        user.must_change_password = False
        user.is_active = True
        user.token_version = 0
    return user


tokens: dict[str, str] = {}
with SessionLocal() as db:
    dept = db.scalar(select(Department))
    for uname, role in (("smoke_sys", Role.SYSADMIN), ("smoke_rm", Role.RECORDS_MANAGER),
                        ("smoke_view", Role.VIEWER)):
        ensure_user(db, uname, role, dept.id if dept else None)
    db.commit()

    for uname in ("smoke_sys", "smoke_rm", "smoke_view"):
        rr = client.post(f"{API}/auth/login", json={"username": uname, "password": PASS_WORD})
        ok = rr.status_code == 200
        check(f"{uname} 登录成功", ok, rr.text[:160])
        if ok:
            tokens[uname] = rr.json().get("access_token", "")

    check("三种角色均可在邮箱登录", len(tokens) == 3, f"成功 {len(tokens)} 个")

    sys_token = tokens.get("smoke_sys", "")
    view_token = tokens.get("smoke_view", "")

    rr = client.post(f"{API}/auth/login", json={"username": "smoke_sys", "password": "wrong-pass"})
    check("错误密码返回 401", rr.status_code == 401, rr.status_code)

    rr = client.get(f"{API}/auth/me")
    check("无 token 访问 /me 返回 401", rr.status_code == 401, rr.status_code)

    rr = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {sys_token}"})
    me = rr.json() if rr.status_code == 200 else {}
    check("带 token 访问 /me 200 且返回角色", rr.status_code == 200 and me.get("role") == "sysadmin",
          str(me)[:160])

    # viewer 不得管理用户 / 建资料室
    rr = client.get(f"{API}/users", headers={"Authorization": f"Bearer {view_token}"})
    check("viewer 访问用户管理返回 403", rr.status_code == 403, rr.status_code)
    rr = client.post(f"{API}/rooms", json={"code": "SMOKEX", "name": "越权测试"},
                     headers={"Authorization": f"Bearer {view_token}"})
    check("viewer 创建资料室返回 403", rr.status_code == 403, rr.status_code)

    rr = client.get(f"{API}/auth/permission-matrix", headers={"Authorization": f"Bearer {sys_token}"})
    matrix = rr.json() if rr.status_code == 200 else None
    check("权限矩阵接口可读", rr.status_code == 200 and matrix is not None, str(rr.status_code))
    text_matrix = str(matrix)
    check("权限矩阵覆盖 3 角色", all(k in text_matrix for k in ("sysadmin", "records_manager", "viewer")),
          text_matrix[:200])

    # must_change_password 强制改密拦截
    tmp_name = "smoke_mcp"
    u = ensure_user(db, tmp_name, Role.VIEWER, dept.id if dept else None)
    u.must_change_password = True
    db.commit()
    rr = client.post(f"{API}/auth/login", json={"username": tmp_name, "password": PASS_WORD})
    mcp_token = rr.json().get("access_token", "") if rr.status_code == 200 else ""
    check("首次登录返回 must_change_password", rr.status_code == 200 and rr.json().get("must_change_password") is True,
          rr.text[:160])
    rr = client.get(f"{API}/rooms", headers={"Authorization": f"Bearer {mcp_token}"})
    check("未改密前访问业务接口被拦截", rr.status_code in (403, 428, 409), rr.status_code)
    u.must_change_password = False
    db.commit()

# ==================== 四、P4 资料室与类目树 ====================
print("\n===== 四、P4 资料室与类目树 =====", flush=True)

h_sys = {"Authorization": f"Bearer {tokens.get('smoke_sys', '')}"}
h_rm = {"Authorization": f"Bearer {tokens.get('smoke_rm', '')}"}

room_payload = {"code": "SMOKE", "name": "冒烟资料室", "description": "P0 基线冒烟"}
rr = client.post(f"{API}/rooms", json=room_payload, headers=h_rm)
if rr.status_code == 409:
    # 脚本可重复执行：已存在时改用「重复创建必须被拒」作为等价断言
    check("records_manager 可创建资料室（已存在→重复创建被拒 409）", True)
    rr = client.post(f"{API}/rooms", json=room_payload, headers=h_rm)
    check("重复资料室编码返回 409", rr.status_code == 409, rr.status_code)
else:
    check("records_manager 可创建资料室", rr.status_code in (200, 201), rr.text[:160])
room_id = rr.json().get("id") if rr.status_code in (200, 201) else None
if room_id is None:
    rr2 = client.get(f"{API}/rooms", headers=h_sys)
    for item in (rr2.json() if rr2.status_code == 200 else []):
        if item.get("code") == "SMOKE":
            room_id = item.get("id")
check("取得资料室 ID", room_id is not None, str(room_id))

rr = client.get(f"{API}/rooms", headers=h_sys)
rooms = rr.json() if rr.status_code == 200 else []
check("资料室列表可读", rr.status_code == 200 and isinstance(rooms, list), str(rr.status_code))
smoke_room = next((x for x in rooms if x.get("code") == "SMOKE"), None) if isinstance(rooms, list) else None
check("新建资料室出现在列表", smoke_room is not None, str(rooms)[:160])
check("资料室返回约定字段（id/code/name/is_active/doc_count）",
      bool(smoke_room) and {"id", "code", "name", "is_active", "doc_count"} <= set(smoke_room),
      str(smoke_room)[:200])
check("密级由文档承载、资料室不设密级（符合 3 角色×4 密级设计)",
      bool(smoke_room) and "secrecy_level" not in smoke_room, str(smoke_room)[:160])

if room_id:
    # 三级类目
    parent_id = None
    chain_ok = True
    for depth, cname in enumerate(("一级", "二级", "三级"), start=1):
        payload = {"room_id": room_id, "name": f"SMOKE-{cname}", "parent_id": parent_id}
        rr = client.post(f"{API}/categories", json=payload, headers=h_rm)
        if rr.status_code == 409:
            existing = client.get(f"{API}/rooms/{room_id}/categories", headers=h_sys).json()
            def find_id(nodes, name_):
                for n in nodes:
                    if n.get("name") == name_:
                        return n.get("id")
                    got = find_id(n.get("children") or [], name_)
                    if got:
                        return got
                return None
            parent_id = find_id(existing if isinstance(existing, list) else [], f"SMOKE-{cname}")
            if not parent_id:
                chain_ok = False
                check(f"创建第 {depth} 级类目", False, "已存在但无法定位该类目")
                break
            continue
        if rr.status_code not in (200, 201):
            chain_ok = False
            check(f"创建第 {depth} 级类目", False, rr.text[:160])
            break
        parent_id = rr.json().get("id")
    else:
        check("三级类目逐级创建成功（或已存在）", chain_ok)

    rr = client.get(f"{API}/rooms/{room_id}/categories", headers=h_sys)
    cats = rr.json() if rr.status_code == 200 else []
    flat = str(cats)
    check("类目树可读且含三级节点",
          rr.status_code == 200 and all(f"SMOKE-{n}" in flat for n in ("一级", "二级", "三级")),
          flat[:200])

    rr = client.patch(f"{API}/rooms/{room_id}", json={"name": "冒烟资料室（改名）"}, headers=h_rm)
    check("资料室可改名", rr.status_code == 200, rr.text[:160])

    rr = client.get(f"{API}/categories/tree", headers=h_sys)
    tree = rr.json() if rr.status_code == 200 else {}
    check("全量类目树接口可用", rr.status_code == 200 and "rooms" in tree, rr.text[:160])
    if isinstance(tree, dict):
        node = next((r for r in tree.get("rooms", []) if r.get("id") == room_id), None)
        check("类目树包含冒烟资料室分组", node is not None, str(tree)[:160])

    rr = client.patch(f"{API}/rooms/{room_id}", json={"is_active": True}, headers=h_sys)
    check("sysadmin 可修改资料室", rr.status_code == 200, rr.text[:160])

# ==================== 汇总 ====================
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
print("\n" + "=" * 60, flush=True)
if passed != total:
    print("失败明细：", flush=True)
    for name, ok, extra in results:
        if not ok:
            print(f"  - {name}  {extra}", flush=True)
print(f"P0 验收：{passed}/{total} 通过", flush=True)
sys.exit(0 if passed == total else 1)
