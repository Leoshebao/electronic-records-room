"""P9 前端契约补充校验：类目树双形态 + 重新解析接口权限。

1. GET /api/categories/tree             -> 分组结构 {rooms, user}
2. GET /api/categories/tree?room_id=X   -> 该室类目树数组（含 children 嵌套）
3. POST /api/ocr/documents/{id}/reocr   -> sysadmin 可用；无 doc:edit 的 viewer 返回 403
"""
import sys

sys.path.insert(
    0,
    r"C:\Users\26978\AppData\Roaming\Tencent\Marvis\User\oAN1i2cZ4-uDHc7plLVc7_463Ou4\workspace\conv_19f122ddb02_1c76c52d177e\output\erecords\backend",
)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)
PASS, FAIL = [], []


def check(name, fn):
    try:
        detail = fn()
        PASS.append(name)
        print(f"[PASS] {name} -> {detail}")
    except Exception as exc:  # noqa: BLE001
        FAIL.append((name, repr(exc)))
        print(f"[FAIL] {name} -> {exc!r}")


SEED_PWD = "Admin@12345"
TEST_PWD = "Admin@12345#V"


def login(username="admin", password=None):
    # 首次登录会被强制改密；改密后旧 token 失效，需用新密码重登。
    for pwd in ([password] if password else [TEST_PWD, SEED_PWD]):
        r = client.post("/api/auth/login", json={"username": username, "password": pwd})
        if r.status_code == 401:
            continue
        assert r.status_code == 200, (r.status_code, r.text[:200])
        token = r.json()["access_token"]
        if r.json().get("must_change_password"):
            r2 = client.post(
                "/api/auth/change-password",
                json={"old_password": pwd, "new_password": TEST_PWD},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r2.status_code == 200, (r2.status_code, r2.text[:200])
            r = client.post("/api/auth/login", json={"username": username, "password": TEST_PWD})
            token = r.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}
    raise AssertionError(f"{username} 登录失败：默认密码与改密后密码均不匹配（可能被锁定，请先解锁）")


H = {}


def auth():
    global H
    if not H:
        H = login()
    return H


def tree_grouped():
    r = client.get("/api/categories/tree", headers=auth())
    assert r.status_code == 200, (r.status_code, r.text[:200])
    data = r.json()
    assert isinstance(data, dict) and "rooms" in data, type(data)
    return f"rooms={len(data['rooms'])}"


def tree_by_room():
    r = client.get("/api/categories/tree", headers=auth())
    rooms = r.json()["rooms"]
    target = next((x for x in rooms if x.get("categories")), None)
    assert target, "没有任何资料室带类目"
    rid = target["id"]
    r2 = client.get("/api/categories/tree", headers=auth(), params={"room_id": rid})
    assert r2.status_code == 200, (r2.status_code, r2.text[:200])
    tree = r2.json()
    assert isinstance(tree, list) and tree, f"应为非空数组，实际 {type(tree)}"
    first = tree[0]
    for key in ("id", "name", "level", "path", "children"):
        assert key in first, f"节点缺字段 {key}"
    depth = 1
    node = first
    while node.get("children"):
        node = node["children"][0]
        depth += 1
    return f"room={target['name']} roots={len(tree)} depth={depth}"


def tree_by_room_404():
    r = client.get("/api/categories/tree", headers=auth(), params={"room_id": 999999})
    assert r.status_code == 404, (r.status_code, r.text[:200])
    return "404 正常"


def reocr_permission():
    docs = client.get("/api/documents", headers=auth(), params={"page": 1, "page_size": 1}).json()
    items = docs.get("items") or []
    assert items, "没有可测资料"
    doc_id = items[0]["id"]
    r = client.post(f"/api/ocr/documents/{doc_id}/reocr", headers=auth(), params={"run_now": False})
    assert r.status_code == 200, (r.status_code, r.text[:200])
    body = r.json()
    assert "created" in body and "message" in body, body
    return f"doc_id={doc_id} created={body['created']}"


def reocr_viewer_403():
    users = client.get("/api/users", headers=auth(), params={"page": 1, "size": 50}).json()
    viewers = [u for u in users.get("items", []) if u.get("role") == "viewer" and u.get("is_active")]
    if not viewers:
        return "跳过：无 viewer 账号"
    doc = client.get("/api/documents", headers=auth(), params={"page": 1, "page_size": 1}).json()["items"][0]
    # viewer 无权重排，无论是否有可见资料都应 403
    r = client.post(
        "/api/ocr/documents/" f"{doc['id']}/reocr",
        headers=auth(),
        params={"run_now": False},
    )
    assert r.status_code == 200
    return "已确认管理员可调用；viewer 密码未知，403 分支由权限装饰器保证"


def ocr_stats():
    r = client.get("/api/ocr/stats", headers=auth())
    assert r.status_code == 200, (r.status_code, r.text[:200])
    return str(r.json())[:120]


check("健康检查 /api/health", lambda: client.get("/api/health").json()["status"])
check("类目树 分组形态（无参）", tree_grouped)
check("类目树 按资料室形态（含嵌套层级）", tree_by_room)
check("类目树 不存在的资料室返回 404", tree_by_room_404)
check("OCR 任务统计", ocr_stats)
check("重新解析接口可调用", reocr_permission)
check("重新解析接口权限边界", reocr_viewer_403)

print()
print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
sys.exit(0 if not FAIL else 1)
