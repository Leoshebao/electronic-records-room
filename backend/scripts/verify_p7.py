"""P7 验收脚本：中文全文检索 / 相关度 / 高亮片段 / 密级隔离 / 索引性能。

运行方式（在 backend 目录，使用会话 venv 的 python）：
    python scripts/verify_p7.py
末行输出 "P7 验收：X/Y 通过"。

说明：本机 PostgreSQL 由 pip 包 pgserver 提供，不含 contrib（无 pg_trgm），
故检索主路径为「单字分词 + GIN(tsvector)」，pg_trgm 仅作为生产环境可选加速。
"""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

os.environ["OCR_WORKER_ENABLED"] = "false"

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402
from passlib.context import CryptContext  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Department, Role, User  # noqa: E402
from app.models.document import Document  # noqa: E402
from app.models.enums import AuditAction, SecrecyLevel  # noqa: E402
from app.models.room import Room  # noqa: E402
from app.models.workflow import AuditLog  # noqa: E402
from app.services import ocr, search as search_service  # noqa: E402
from app.services.documents import refresh_search_text  # noqa: E402

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASS_WORD = "Verify@12345"
ROOM_CODE = "P7T"
results: list[tuple[str, bool, str]] = []

TEXT_A = "本工程混凝土浇筑专项方案采用分层连续浇筑工艺，坍落度控制在180mm，振捣密实。"
TITLE_A = "混凝土浇筑专项方案"
TEXT_B = "竣工验收报告：现场整改已全部完成，建设单位同意竣工验收，资料移交档案室。"
TITLE_B = "竣工验收报告"
TEXT_C = "内部审计底稿：专项经费使用明细与审批流程核查记录。"
TITLE_C = "内部审计底稿"


def check(name: str, ok: bool, extra: str = "") -> None:
    results.append((name, bool(ok), extra))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  -> ' + str(extra)[:200]) if not ok else ''}", flush=True)


def ensure_user(db, username: str, role: Role, dept_id: int | None) -> None:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(username=username, full_name=f"P7{role.value}", password_hash=pwd.hash(PASS_WORD),
                    role=role, department_id=dept_id, is_active=True, must_change_password=False)
        db.add(user)
    else:
        user.password_hash = pwd.hash(PASS_WORD)
        user.is_active = True
        user.must_change_password = False
        user.token_version = 0
    db.flush()


def prepare_db() -> int:
    db = SessionLocal()
    try:
        dept = db.scalar(select(Department).where(Department.code == "ZH"))
        if dept is None:
            dept = Department(name="综合部", code="ZH", sort_order=10)
            db.add(dept)
            db.flush()
        ensure_user(db, "p7_admin", Role.SYSADMIN, dept.id)
        ensure_user(db, "p7_viewer", Role.VIEWER, dept.id)
        room = db.scalar(select(Room).where(Room.code == ROOM_CODE))
        if room is None:
            room = Room(name="P7验收资料室", code=ROOM_CODE, location="测试位置")
            db.add(room)
            db.flush()
        db.commit()
        return room.id
    finally:
        db.close()


def login(client: TestClient, username: str) -> str:
    r = client.post("/api/auth/login", json={"username": username, "password": PASS_WORD})
    assert r.status_code == 200, f"登录失败 {username}: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


def upload(client: TestClient, token: str, room_id: int, title: str,
           file_name: str, body: str, level: str = "internal") -> dict:
    r = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        data={"room_id": room_id, "title": title, "secrecy_level": level},
        files=[("files", (file_name, body.encode("utf-8"), "text/plain"))],
    )
    assert r.status_code == 201, f"上传失败: {r.status_code} {r.text[:300]}"
    return r.json()


def refresh(doc_id: int) -> None:
    """模拟后台文本提取完成：抽取文件文本 → 刷新检索列。"""
    db = SessionLocal()
    try:
        doc = db.get(Document, doc_id)
        for f in doc.files:
            if not f.ocr_text:
                try:
                    f.ocr_text = ocr.extract_text(f.rel_path, f.ext).text or None
                except Exception:  # noqa: BLE001 - 提取失败时保持空，由断言暴露
                    f.ocr_text = None
        db.flush()
        refresh_search_text(db, doc)
        db.commit()
    finally:
        db.close()


def search(client: TestClient, token: str, q: str, **params) -> dict:
    r = client.get("/api/search", params={"q": q, **params},
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, f"检索失败 {q}: {r.status_code} {r.text[:300]}"
    return r.json()


def main() -> int:
    room_id = prepare_db()

    # ---------- 0. 索引与预处理单元校验 ----------
    db = SessionLocal()
    try:
        rev = db.scalar(text("select version_num from alembic_version"))
        check("迁移已到 0004_fts_grams 或更高", rev is not None and rev >= "0004", rev)
        has_col = db.scalar(text(
            "select count(*) from information_schema.columns "
            "where table_name='documents' and column_name='search_grams'"
        ))
        check("documents.search_grams 列存在", bool(has_col), has_col)
        idx = db.scalar(text("select to_regclass('public.ix_doc_search_grams_gin')"))
        check("GIN 全文索引已建立", idx is not None, idx)
        check("fts_available 返回可用", search_service.fts_available(db))
    finally:
        db.close()

    check("中文逐字分词", search_service.make_grams("竣工验收") == "竣 工 验 收",
          search_service.make_grams("竣工验收"))
    check("英文保留整词", search_service.make_grams("PDF文件A1") == "pdf 文 件 a1",
          search_service.make_grams("PDF文件A1"))
    check("短语查询词序连接", search_service.make_tsquery("竣工") == "竣 <-> 工",
          search_service.make_tsquery("竣工"))
    check("关键词按空白与标点切分",
          search_service.split_keywords("竣工，验收  方案") == ["竣工", "验收", "方案"],
          search_service.split_keywords("竣工，验收  方案"))
    check("关键词数量上限 8",
          len(search_service.split_keywords(" ".join(f"k{i}" for i in range(20)))) == 8)

    with TestClient(app) as client:
        t_admin = login(client, "p7_admin")
        t_view = login(client, "p7_viewer")
        HA = {"Authorization": f"Bearer {t_admin}"}
        HV = {"Authorization": f"Bearer {t_view}"}

        # ---------- 1. 权限 ----------
        r = client.get("/api/search", params={"q": "竣工"})
        check("未登录检索返回 401", r.status_code == 401, r.status_code)

        # ---------- 2. 入库与检索列生成 ----------
        d_a = upload(client, t_admin, room_id, TITLE_A, "浇筑方案.txt", TEXT_A)
        d_b = upload(client, t_admin, room_id, TITLE_B, "竣工报告.txt", TEXT_B)
        d_c = upload(client, t_admin, room_id, TITLE_C, "审计底稿.txt", TEXT_C, level="secret")
        for d in (d_a, d_b, d_c):
            refresh(d["id"])

        db = SessionLocal()
        try:
            row = db.get(Document, d_a["id"])
            check("入库自动生成 search_grams", bool(row.search_grams) and "坍" in row.search_grams,
                  (row.search_grams or "")[:60])
            check("search_grams 含英文整词不受影响",
                  "180mm" in (row.search_grams or "") or "180" in (row.search_grams or ""),
                  (row.search_grams or "")[:60])
        finally:
            db.close()

        # ---------- 3. 正文关键词命中 ----------
        body = search(client, t_admin, "坍落度")
        ids = [it["id"] for it in body["items"]]
        check("正文中文关键词可命中", d_a["id"] in ids, ids)
        check("响应回显切分后的关键词", body["keywords"] == ["坍落度"], body["keywords"])
        check("响应标注走全文索引", body.get("fts") is True, body.get("fts"))
        hit = next((it for it in body["items"] if it["id"] == d_a["id"]), {})
        check("命中片段含 <em> 高亮", "<em>坍落度</em>" in (hit.get("snippet") or ""), hit.get("snippet"))
        check("命中字段标记 search_text",
              "search_text" in (hit.get("matched") or []), hit.get("matched"))

        body = search(client, t_admin, "竣工验收")
        ids = [it["id"] for it in body["items"]]
        check("跨标点短语仍可命中", d_b["id"] in ids, ids)

        # ---------- 4. 词序与误命中 ----------
        body = search(client, t_admin, "工竣")
        check("词序颠倒不误命中（短语语义）", body["meta"]["total"] == 0, body["meta"]["total"])
        body = search(client, t_admin, "柠檬水")
        check("无关关键词零命中", body["meta"]["total"] == 0, body["meta"]["total"])

        # ---------- 5. 多关键词 AND ----------
        body = search(client, t_admin, "竣工验收 整改")
        check("多关键词同时命中返回结果", body["meta"]["total"] >= 1 and d_b["id"] in [i["id"] for i in body["items"]],
              body["meta"]["total"])
        body = search(client, t_admin, "竣工验收 坍落度")
        check("多关键词任一缺失即不返回", body["meta"]["total"] == 0, body["meta"]["total"])

        # ---------- 6. 相关度排序 ----------
        body = search(client, t_admin, "浇筑")
        scores = [it["score"] for it in body["items"]]
        check("按相关度降序返回", scores == sorted(scores, reverse=True), scores)
        body = search(client, t_admin, "专项", sort="relevance")
        top = body["items"][0] if body["items"] else {}
        check("题名命中权重高于正文", top.get("id") == d_a["id"], top.get("title"))

        # ---------- 7. 分页与排序 ----------
        body = search(client, t_admin, "竣工", size=1, page=1)
        check("分页 size 生效", len(body["items"]) <= 1, len(body["items"]))
        check("分页 meta 计算页数", body["meta"]["pages"] >= 1, body["meta"])
        body_asc = search(client, t_admin, "竣工", sort="created_at", order="asc")
        check("排序参数生效", body_asc["items"][0]["created_at"] <= body_asc["items"][-1]["created_at"],
              [i["created_at"] for i in body_asc["items"]])

        # ---------- 8. 密级隔离 ----------
        body = search(client, t_admin, "内部审计")
        check("管理员可检索机密资料", d_c["id"] in [i["id"] for i in body["items"]], body["meta"]["total"])
        body = search(client, t_view, "内部审计")
        check("查阅者检索不到机密资料", d_c["id"] not in [i["id"] for i in body["items"]], body["meta"]["total"])
        r = client.get("/api/search", params={"q": "竣工", "secrecy_level": "secret"}, headers=HV)
        check("越权密级过滤参数返回 403", r.status_code == 403, r.status_code)

        # ---------- 9. 联想 ----------
        r = client.get("/api/search/suggest", params={"q": "竣工", "limit": 5}, headers=HV)
        sug = r.json() if r.status_code == 200 else []
        check("联想接口返回题名", r.status_code == 200 and any(s["title"] == TITLE_B for s in sug), r.text[:200])
        r = client.get("/api/search/suggest", params={"q": "内部审计"}, headers=HV)
        sug = r.json() if r.status_code == 200 else []
        check("联想不泄露越权密级", all(s["secrecy_level"] != "secret" for s in sug), sug)

        # ---------- 10. 审计 ----------
        db = SessionLocal()
        try:
            cnt = db.scalar(
                select(text("count(*)")).select_from(AuditLog).where(
                    AuditLog.action == AuditAction.DOC_SEARCH.value,
                    AuditLog.username == "p7_admin",
                )
            ) or 0
            check("检索行为写入审计", cnt > 0, cnt)
            row = db.scalars(
                select(AuditLog).where(AuditLog.action == AuditAction.DOC_SEARCH.value).order_by(AuditLog.id.desc())
            ).first()
            check("审计记录含关键词与耗时",
                  bool(row and row.detail and "keywords" in row.detail and "took_ms" in row.detail),
                  row.detail if row else None)
        finally:
            db.close()

        # ---------- 11. 统计自检 ----------
        r = client.get("/api/search/stats", headers=HA)
        st = r.json() if r.status_code == 200 else {}
        check("统计接口报告全文索引可用", r.status_code == 200 and st.get("fts") is True, r.text[:200])
        check("统计列出 GIN 索引名",
              any("ix_doc_search_grams_gin" == n for n in (st.get("indexes") or [])), st.get("indexes"))
        check("统计报告已索引资料数", (st.get("indexed_docs") or 0) >= 3, st.get("indexed_docs"))
        r = client.get("/api/search/stats", headers=HV)
        check("查阅者无权查看检索统计 403", r.status_code == 403, r.status_code)

    # ---------- 12. 索引使用与性能：灌 1000 条后检索 ----------
    db = SessionLocal()
    try:
        sub = db.scalar(text("select id from rooms where code = :c"), {"c": ROOM_CODE})
        admin_id = db.scalar(text("select id from users where username = 'p7_admin'"))
        # 幂等：清掉上一轮遗留的压测资料
        db.execute(text("delete from documents where doc_no like 'P7-BULK-%'"))
        db.flush()
        bulk = []
        for i in range(1000):
            body = f"批量压测资料{i}：市政道路沥青摊铺温度控制与压实度检测记录{i}"
            bulk.append({
                "room_id": sub,
                "title": f"压测资料{i}",
                "doc_no": f"P7-BULK-{i:04d}",
                "status": "active",
                "secrecy_level": "internal",
                "created_by": admin_id,
                "search_text": body,
                "search_grams": search_service.make_grams(body),
                "is_deleted": False,
                "view_count": 0,
                "download_count": 0,
                "file_count": 0,
                "version_no": 1,
            })
        db.execute(Document.__table__.insert(), bulk)
        db.commit()
        check("批量灌入 1000 条压测资料", True)

        # 索引计划
        db.execute(text("set local enable_seqscan = off"))
        plan = db.execute(text(
            "explain select id from documents where to_tsvector('simple', coalesce(search_grams,'')) "
            "@@ to_tsquery('simple', '沥 <-> 青')"
        )).scalars().all()
        check("查询计划命中 GIN 索引", any("ix_doc_search_grams_gin" in p for p in plan),
              " | ".join(plan)[:200])
        db.rollback()

        started = time.perf_counter()
        rows = db.execute(text(
            "select id from documents where to_tsvector('simple', coalesce(search_grams,'')) "
            "@@ to_tsquery('simple', '压 <-> 实 <-> 度') limit 20"
        )).all()
        cost_ms = (time.perf_counter() - started) * 1000
        check("千级资料检索命中结果", len(rows) > 0, len(rows))
        check("千级资料检索耗时 < 2000ms", cost_ms < 2000, f"{cost_ms:.0f}ms")
    finally:
        db.close()

    ok = sum(1 for _, passed, _ in results if passed)
    total = len(results)
    print(f"P7 验收：{ok}/{total} 通过")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
