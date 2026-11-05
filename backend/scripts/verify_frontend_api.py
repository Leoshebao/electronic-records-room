"""接口层端到端验收：以 admin 登录后遍历前端各页面依赖的全部接口。

覆盖：健康检查、认证、资料室/类目、用户/部门、文档、审计、备份、OCR、检索、统计、借阅。
判据：HTTP 200（或预期 4xx）且返回体结构符合前端取值方式，全部通过 exit=0。
"""
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from app.main import app

PASS, FAIL = [], []


def check(name, fn):
    try:
        detail = fn()
        PASS.append((name, detail))
        print(f"[PASS] {name} -> {detail}")
    except Exception as exc:  # noqa: BLE001
        FAIL.append((name, f"{type(exc).__name__}: {exc}"))
        print(f"[FAIL] {name} -> {type(exc).__name__}: {exc}")
        traceback.print_exc(limit=2)


def main() -> int:
    client = TestClient(app)
    state = {}

    # 1) 未登录必须 401
    def unauth():
        r = client.get("/api/rooms")
        assert r.status_code == 401, r.status_code
        return "401"

    check("未登录访问 /rooms 返回 401", unauth)

    # 2) 登录（首次登录需完成强制改密，改密后 token 失效需重登）
    SEED_PWD = "Admin@12345"
    TEST_PWD = "Admin@12345#V"

    def do_login(pwd):
        r = client.post("/api/auth/login", json={"username": "admin", "password": pwd})
        if r.status_code != 200:
            return None, r
        data = r.json()
        state["h"] = {"Authorization": f"Bearer {data['access_token']}"}
        state["user"] = data.get("user") or {}
        return data, r

    def login():
        data, r = do_login(SEED_PWD)
        if data is None:
            data, r = do_login(TEST_PWD)
        assert data is not None, ("登录失败", r.status_code, r.text[:300])
        u = state["user"]
        if u.get("must_change_password"):
            c = client.post(
                "/api/auth/change-password",
                headers=state["h"],
                json={"old_password": SEED_PWD, "new_password": TEST_PWD},
            )
            assert c.status_code == 200, ("改密失败", c.status_code, c.text[:300])
            data, r = do_login(TEST_PWD)
            assert data is not None, ("改密后重登失败", r.status_code, r.text[:300])
            u = state["user"]
        return f"role={u.get('role')} must_change={u.get('must_change_password')}"

    check("登录（含首次强制改密流程）", login)

    H = lambda: state["h"]  # noqa: E731

    def must_change_password():
        u = state["user"]
        assert u.get("must_change_password") is not True, "管理员仍处于强制改密状态，需先改密"
        return "ok"

    check("管理员非强制改密状态", must_change_password)

    # 3) 健康检查 / 系统自检
    def health():
        out = {}
        for p in ("/api/health", "/api/health/db", "/api/health/storage"):
            r = client.get(p, headers=H())
            assert r.status_code == 200, (p, r.status_code, r.text[:200])
            out[p] = r.json()
        return json.dumps(out, ensure_ascii=False)[:160]

    check("健康检查三接口", health)

    def system_check():
        out = {}
        r = client.get("/api/ocr/engine", headers=H())
        assert r.status_code == 200, (r.status_code, r.text[:200])
        out["ocr_engine"] = r.json()
        r = client.get("/api/ocr/tasks", headers=H())
        assert r.status_code == 200, (r.status_code, r.text[:200])
        out["ocr_tasks"] = "ok"
        r = client.get("/api/search/stats", headers=H())
        assert r.status_code == 200, (r.status_code, r.text[:200])
        out["search_stats"] = r.json()
        return json.dumps(out, ensure_ascii=False)[:160]

    check("系统自检依赖接口", system_check)

    # 4) 资料室 / 类目
    def rooms():
        r = client.get("/api/rooms", headers=H())
        assert r.status_code == 200, (r.status_code, r.text[:200])
        rooms = r.json()
        assert isinstance(rooms, list) and rooms, "资料室列表为空"
        state["room"] = rooms[0]
        # 分组形态（无参）：左侧导航一次加载
        r = client.get("/api/categories/tree", headers=H())
        assert r.status_code == 200, (r.status_code, r.text[:200])
        grouped = r.json()
        assert isinstance(grouped, dict) and "rooms" in grouped, grouped
        # 按资料室形态（带 room_id）：前端资料室/文档页使用，必须是数组
        rid = state["room"]["id"]
        r = client.get("/api/categories/tree", headers=H(), params={"room_id": rid})
        assert r.status_code == 200, (r.status_code, r.text[:200])
        tree = r.json()
        assert isinstance(tree, list), f"带 room_id 应返回数组，实际 {type(tree)}"
        state["tree"] = tree
        return f"rooms={len(rooms)} grouped={len(grouped['rooms'])} tree_roots={len(tree)}"

    check("资料室列表 + 类目树", rooms)

    def room_categories():
        rid = state["room"]["id"]
        r = client.get(f"/api/rooms/{rid}/categories", headers=H())
        assert r.status_code == 200, (r.status_code, r.text[:200])
        return f"{len(r.json())}"

    check("资料室下类目", room_categories)

    # 5) 用户 / 部门
    def users():
        r = client.get("/api/users", headers=H(), params={"page": 1, "page_size": 10})
        assert r.status_code == 200, (r.status_code, r.text[:200])
        body = r.json()
        assert "items" in body, body.keys()
        r = client.get("/api/departments", headers=H())
        assert r.status_code == 200, (r.status_code, r.text[:200])
        depts = r.json()
        state["dept"] = depts[0] if depts else None
        return f"users_total={body.get('total')} depts={len(depts)}"

    check("用户分页 + 部门列表", users)

    # 6) 文档
    def documents():
        r = client.get("/api/documents", headers=H(), params={"page": 1, "page_size": 5})
        assert r.status_code == 200, (r.status_code, r.text[:200])
        body = r.json()
        assert "items" in body, body.keys()
        items = body["items"]
        if items:
            did = items[0]["id"]
            d = client.get(f"/api/documents/{did}", headers=H())
            assert d.status_code == 200, (d.status_code, d.text[:200])
            assert "versions" in d.json(), "详情缺 versions 字段"
            state["doc"] = items[0]
        return f"total={body.get('total')} items={len(items)}"

    check("文档列表 + 详情(含版本)", documents)

    def storage_usage():
        r = client.get("/api/documents/storage/usage", headers=H())
        assert r.status_code == 200, (r.status_code, r.text[:200])
        return json.dumps(r.json(), ensure_ascii=False)[:120]

    check("存储用量", storage_usage)

    # 7) 审计
    def audit():
        r = client.get("/api/audit/logs", headers=H(), params={"page": 1, "page_size": 10})
        assert r.status_code == 200, (r.status_code, r.text[:200])
        assert "items" in r.json(), r.json().keys()
        r = client.get("/api/audit/actions", headers=H())
        assert r.status_code == 200, (r.status_code, r.text[:200])
        acts = r.json()
        r = client.get("/api/audit/summary", headers=H())
        assert r.status_code == 200, (r.status_code, r.text[:200])
        s = r.json()
        for k in ("total", "today", "failed", "by_action", "by_user"):
            assert k in s, f"summary 缺 {k}"
        return f"actions={len(acts)} total={s['total']}"

    check("审计日志 + 动作字典 + 统计", audit)

    def stats_overview():
        r = client.get("/api/stats/overview", headers=H())
        assert r.status_code == 200, (r.status_code, r.text[:200])
        return json.dumps(r.json(), ensure_ascii=False)[:120]

    check("统计概览", stats_overview)

    # 8) 备份
    def backups():
        r = client.get("/api/backups", headers=H())
        assert r.status_code == 200, (r.status_code, r.text[:200])
        rows = r.json()
        return f"records={len(rows)}"

    check("备份记录列表", backups)

    # 9) 检索
    def search():
        r = client.get("/api/search", headers=H(), params={"q": "档案", "page": 1, "page_size": 5})
        assert r.status_code == 200, (r.status_code, r.text[:200])
        r2 = client.get("/api/search/suggest", headers=H(), params={"q": "档"})
        assert r2.status_code == 200, (r2.status_code, r2.text[:200])
        return f"hits={len(r.json().get('items', []))} suggest={len(r2.json())}"

    check("检索 + 联想", search)

    # 10) 借阅
    def borrow():
        r = client.get("/api/borrow/requests", headers=H(), params={"page": 1, "page_size": 5})
        assert r.status_code == 200, (r.status_code, r.text[:200])
        assert "items" in r.json(), r.json().keys()
        r2 = client.get("/api/borrow/mine", headers=H())
        assert r2.status_code == 200, (r2.status_code, r2.text[:200])
        r3 = client.get("/api/borrow/levels", headers=H())
        assert r3.status_code == 200, (r3.status_code, r3.text[:200])
        return f"all={r.json().get('total')} mine={len(r2.json())} levels={len(r3.json())}"

    check("借阅列表 + 我的申请 + 密级", borrow)

    # 11) 权限矩阵
    def matrix():
        r = client.get("/api/auth/permission-matrix", headers=H())
        assert r.status_code == 200, (r.status_code, r.text[:200])
        m = r.json()
        return f"keys={list(m)[:4]}"

    check("权限矩阵", matrix)

    print()
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for n, e in FAIL:
            print("  FAIL:", n, e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
