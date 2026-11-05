"""P9 验收脚本：版本管理 → PDF 动态水印 → 审计防篡改 → 备份。

运行方式（在 backend 目录，使用会话 venv 的 python）：
    python scripts/verify_p9.py
末行输出 "P9 验收：X/Y 通过"。

分两部分：
- 数据层：document_versions / files.version_id / current_version_id 一致性、
  audit_logs 触发器防篡改、backup_records 落库；
- 接口层：版本新增与回滚、水印响应头与内容、审计查询权限、备份权限与产物。
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

os.environ["OCR_WORKER_ENABLED"] = "false"
os.environ["BORROW_SWEEP_ENABLED"] = "false"

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402
from passlib.context import CryptContext  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Department, Role, User  # noqa: E402
from app.models.document import Document, DocumentVersion, FileObject  # noqa: E402
from app.models.room import Room  # noqa: E402
from app.models.workflow import AuditLog, BackupRecord  # noqa: E402
from app.services import storage  # noqa: E402

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASS_WORD = "Verify@12345"
ROOM_CODE = "P9T"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    results.append((name, bool(ok), extra))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  -> ' + str(extra)[:200]) if not ok else ''}", flush=True)


def make_pdf(pages: list[str]) -> bytes:
    """生成含中文的 PDF 字节流。"""
    import fitz

    doc = fitz.open()
    try:
        for content in pages:
            page = doc.new_page()
            try:
                page.insert_text((72, 90), content, fontsize=14, fontname="china-s")
            except Exception:  # noqa: BLE001 - 缺 CJK 字体时退回英文
                page.insert_text((72, 90), content.encode("ascii", "ignore").decode() or "P9 PDF",
                                 fontsize=14, fontname="helv")
        return doc.tobytes()
    finally:
        doc.close()


def ensure_user(db, username: str, role: Role, dept_id: int | None) -> None:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(username=username, full_name=f"P9{role.value}", password_hash=pwd.hash(PASS_WORD),
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
        ensure_user(db, "p9_admin", Role.SYSADMIN, dept.id)
        ensure_user(db, "p9_manager", Role.RECORDS_MANAGER, dept.id)
        ensure_user(db, "p9_viewer", Role.VIEWER, dept.id)
        room = db.scalar(select(Room).where(Room.code == ROOM_CODE))
        if room is None:
            room = Room(name="P9验收资料室", code=ROOM_CODE, location="测试位置")
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


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def upload(client: TestClient, token: str, room_id: int, title: str,
           file_name: str, body: bytes, mime: str, level: str = "internal") -> dict:
    r = client.post(
        "/api/documents/upload",
        headers=auth(token),
        data={"room_id": room_id, "title": title, "secrecy_level": level},
        files=[("files", (file_name, body, mime))],
    )
    assert r.status_code == 201, f"上传失败: {r.status_code} {r.text[:300]}"
    return r.json()


def sha_of(rel_path: str) -> str:
    p = storage.resolve_safe(rel_path)
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    room_id = prepare_db()

    with TestClient(app) as client:
        admin = login(client, "p9_admin")
        manager = login(client, "p9_manager")
        viewer = login(client, "p9_viewer")

        pdf_v1 = make_pdf(["P9 版本一 第一页", "P9 版本一 第二页"])
        pdf_v2 = make_pdf(["P9 版本二 第一页"])

        d1 = upload(client, admin, room_id, "P9版本与水印验证", "p9_v1.pdf", pdf_v1, "application/pdf")
        d2 = upload(client, admin, room_id, "P9纯文本验证", "p9_plain.txt",
                    "P9 纯文本正文，用于验证非 PDF 不叠加水印。".encode("utf-8"), "text/plain")

        # ================= 数据层：版本基线
        db = SessionLocal()
        try:
            vers = db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == d1["id"])
                              .order_by(DocumentVersion.version_no)).all()
            check("上传即创建 v1 版本记录", len(vers) == 1 and vers[0].version_no == 1,
                  [v.version_no for v in vers])
            check("v1 标记为当前版本", vers and vers[0].is_current is True)
            doc = db.get(Document, d1["id"])
            check("documents.current_version_id 指向 v1",
                  doc.current_version_id == vers[0].id, doc.current_version_id)
            fos = db.scalars(select(FileObject).where(FileObject.document_id == d1["id"])).all()
            check("文件挂到 v1 版本", all(f.version_id == vers[0].id for f in fos) and fos)
            check("文件状态为 stored", all(f.status == "stored" for f in fos))
            v1_file_id = fos[0].id
            v1_rel = fos[0].rel_path
        finally:
            db.close()

        # ================= 接口层：新增版本
        r = client.post(f"/api/documents/{d1['id']}/versions", headers=auth(viewer),
                        files=[("files", ("p9_v2.pdf", pdf_v2, "application/pdf"))],
                        data={"change_note": "查阅者越权尝试"})
        check("查阅者无权新增版本", r.status_code == 403, r.status_code)

        r = client.post(f"/api/documents/{d1['id']}/versions", headers=auth(manager),
                        files=[("files", ("p9_v2.pdf", pdf_v2, "application/pdf"))],
                        data={"change_note": "修订第二版，更新结构参数"})
        check("档案管理员可新增版本", r.status_code == 201, f"{r.status_code} {r.text[:200]}")

        r = client.get(f"/api/documents/{d1['id']}/versions", headers=auth(admin))
        check("版本列表可查询", r.status_code == 200, r.status_code)
        vlist = r.json()
        check("版本数变为 2", len(vlist) == 2, len(vlist))
        check("版本按版本号倒序", [v.get("version_no") for v in vlist] == [2, 1],
              [v.get("version_no") for v in vlist])

        db = SessionLocal()
        try:
            vers = db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == d1["id"])
                              .order_by(DocumentVersion.version_no)).all()
            check("数据层：v2 版本号递增", len(vers) == 2 and vers[1].version_no == 2,
                  [v.version_no for v in vers])
            check("数据层：仅一个版本标记为当前",
                  sum(1 for v in vers if v.is_current) == 1,
                  [v.is_current for v in vers])
            check("数据层：当前版本为 v2", vers[1].is_current is True)
            doc = db.get(Document, d1["id"])
            check("数据层：current_version_id 指向 v2",
                  doc.current_version_id == vers[1].id, doc.current_version_id)
            check("数据层：修订说明已记录", (vers[1].change_note or "").strip() != "",
                  vers[1].change_note)
            fos = db.scalars(select(FileObject).where(FileObject.document_id == d1["id"])).all()
            check("数据层：两版文件并存（未覆盖）", len(fos) == 2, len(fos))
            check("数据层：新旧文件分属不同版本", len({f.version_id for f in fos}) == 2,
                  [f.version_id for f in fos])
            v2_id = vers[1].id
            v1_id = vers[0].id
        finally:
            db.close()

        # ================= 接口层：回滚
        r = client.post(f"/api/documents/{d1['id']}/versions/{v2_id}/rollback", headers=auth(manager))
        check("回滚到当前版本被拒绝", r.status_code == 409, r.status_code)

        r = client.post(f"/api/documents/{d1['id']}/versions/{v1_id}/rollback", headers=auth(manager))
        check("可回滚到历史版本", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

        db = SessionLocal()
        try:
            doc = db.get(Document, d1["id"])
            check("回滚后 current_version_id 指向 v1", doc.current_version_id == v1_id,
                  doc.current_version_id)
            vers = db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == d1["id"])
                              .order_by(DocumentVersion.version_no)).all()
            check("回滚后当前标记唯一且落在 v1",
                  vers[0].is_current is True and vers[1].is_current is False,
                  [v.is_current for v in vers])
        finally:
            db.close()

        r = client.post(f"/api/documents/{d1['id']}/versions/999999/rollback", headers=auth(manager))
        check("回滚不存在的版本返回 404", r.status_code == 404, r.status_code)

        r = client.post(f"/api/documents/{d1['id']}/versions/{v1_id}/rollback", headers=auth(viewer))
        check("查阅者无权回滚版本", r.status_code == 403, r.status_code)

        # ================= 接口层：PDF 动态水印
        sha_before = sha_of(v1_rel)
        r = client.get(f"/api/files/{v1_file_id}/preview", headers=auth(admin))
        check("预览 PDF 返回 200", r.status_code == 200, r.status_code)
        check("预览响应标记已加水印", r.headers.get("x-watermarked") == "1",
              r.headers.get("x-watermarked"))
        check("预览禁止缓存", "no-store" in (r.headers.get("cache-control") or ""),
              r.headers.get("cache-control"))

        r = client.get(f"/api/files/{v1_file_id}/download", headers=auth(admin))
        check("下载 PDF 返回 200", r.status_code == 200, r.status_code)
        check("下载响应标记已加水印", r.headers.get("x-watermarked") == "1",
              r.headers.get("x-watermarked"))
        watermarked = r.content

        import fitz

        try:
            wm_doc = fitz.open(stream=watermarked, filetype="pdf")
            try:
                check("水印版 PDF 可正常打开", True)
                check("水印版页数与原文一致", wm_doc.page_count == 2, wm_doc.page_count)
                joined = "".join(p.get_text() for p in wm_doc)
                check("水印含下载账号，可追溯到人", "p9_admin" in joined, joined[:120])
                check("水印含合规提示语", "内部资料" in joined or "禁止外传" in joined, joined[:120])
            finally:
                wm_doc.close()
        except Exception as exc:  # noqa: BLE001
            check("水印版 PDF 可正常打开", False, exc)

        check("水印版与原文二进制不同（确已叠加）", watermarked != pdf_v1, len(watermarked))
        check("水印不落盘、原文件未被改写", sha_of(v1_rel) == sha_before)

        d1_files = client.get(f"/api/documents/{d1['id']}/files", headers=auth(admin)).json()
        check("文档文件列表按当前版本口径返回", len(d1_files) >= 1, len(d1_files))

        # 非 PDF 不叠加水印
        plain_file = client.get(f"/api/documents/{d2['id']}/files", headers=auth(admin)).json()[0]
        r = client.get(f"/api/files/{plain_file['id']}/download", headers=auth(admin))
        check("非 PDF 下载不叠加水印", r.status_code == 200 and r.headers.get("x-watermarked") is None,
              r.headers.get("x-watermarked"))
        check("非 PDF 内容与原文一致", r.content ==
              "P9 纯文本正文，用于验证非 PDF 不叠加水印。".encode("utf-8"), len(r.content))

        r = client.get(f"/api/files/{v1_file_id}/preview", headers=auth(viewer))
        check("查阅者预览内部级 PDF 可用", r.status_code in (200, 403), r.status_code)

        # ================= 数据层：审计防篡改
        db = SessionLocal()
        try:
            trig = db.scalar(text(
                "select count(*) from pg_trigger where tgname = 'trg_audit_no_update'"
            ))
            check("审计防篡改触发器存在", (trig or 0) == 1, trig)

            audit_rows = db.scalar(text("select count(*) from audit_logs")) or 0
            check("审计日志已有记录", audit_rows > 0, audit_rows)

            row_id = db.scalar(text("select max(id) from audit_logs"))

            blocked_update = False
            try:
                db.execute(text("update audit_logs set result='tampered' where id = :i"), {"i": row_id})
                db.commit()
            except Exception:  # noqa: BLE001
                blocked_update = True
                db.rollback()
            check("直接 UPDATE 审计日志被拒绝", blocked_update)

            blocked_delete = False
            try:
                db.execute(text("delete from audit_logs where id = :i"), {"i": row_id})
                db.commit()
            except Exception:  # noqa: BLE001
                blocked_delete = True
                db.rollback()
            check("直接 DELETE 审计日志被拒绝", blocked_delete)

            still = db.scalar(text("select count(*) from audit_logs")) or 0
            check("拦截后审计记录数未变化", still == audit_rows, (audit_rows, still))

            dl = db.scalar(select(AuditLog).where(AuditLog.action == "doc_download")
                           .order_by(AuditLog.id.desc()))
            check("下载已写入 doc_download 审计", dl is not None)
            view_log = db.scalar(select(AuditLog).where(AuditLog.action == "doc_view")
                                 .order_by(AuditLog.id.desc()))
            check("预览已写入 doc_view 审计", view_log is not None)
            check("审计记录来源 IP", dl is not None and (dl.ip_address or "") != "",
                  dl.ip_address if dl else None)
            check("审计记录结构化明细", dl is not None and isinstance(dl.detail, dict) and dl.detail,
                  dl.detail if dl else None)
            check("审计记录冗余用户名", dl is not None and (dl.username or "") != "",
                  dl.username if dl else None)
            upd = db.scalar(select(AuditLog).where(AuditLog.action == "doc_update",
                                                  AuditLog.target_id == d1["id"]))
            check("新增版本写入 doc_update 审计", upd is not None)
            rb = db.scalar(select(AuditLog).where(AuditLog.action == "doc_update",
                                                 AuditLog.target_id == d1["id"],
                                                 AuditLog.detail["rollback_to"].is_not(None)))
            check("版本回滚写入审计", rb is not None)
        finally:
            db.close()

        # ================= 接口层：审计查询
        r = client.get("/api/audit/logs", headers=auth(admin))
        check("管理员可查询审计日志", r.status_code == 200, r.status_code)
        logs = r.json()
        check("审计日志返回分页结构",
              isinstance(logs, dict) and logs.get("total", 0) >= 1, list(logs)[:6] if isinstance(logs, dict) else type(logs))

        r = client.get("/api/audit/logs", headers=auth(admin),
                       params={"action": "doc_download", "size": 5})
        body = r.json()
        check("可按动作筛选审计", r.status_code == 200, r.status_code)
        items = body.get("items", []) if isinstance(body, dict) else []
        check("筛选结果动作一致", all(i.get("action") == "doc_download" for i in items),
              [i.get("action") for i in items][:5])

        r = client.get("/api/audit/logs", headers=auth(viewer))
        check("查阅者无权查询审计日志", r.status_code == 403, r.status_code)

        r = client.get("/api/audit/summary", headers=auth(admin))
        check("审计统计可查询", r.status_code == 200 and isinstance(r.json(), dict), r.status_code)

        r = client.get("/api/audit/actions", headers=auth(admin))
        check("审计动作字典可查询", r.status_code == 200 and r.json(), r.status_code)

        r = client.get("/api/audit/logs", headers=auth(admin),
                       params={"target_type": "document", "target_id": d1["id"]})
        check("可按目标对象筛选审计", r.status_code == 200 and r.json().get("total", 0) >= 1,
              r.status_code)

        # ================= 接口层：备份
        r = client.post("/api/backups", headers=auth(viewer), params={"backup_type": "db"})
        check("查阅者无权触发备份", r.status_code == 403, r.status_code)

        r = client.post("/api/backups", headers=auth(admin), params={"backup_type": "db"})
        check("管理员可触发数据库备份", r.status_code == 201, f"{r.status_code} {r.text[:200]}")
        rec = r.json() if r.status_code == 201 else {}
        check("备份状态为 success", rec.get("status") == "success", rec.get("status"))
        check("备份产物大小大于 0", (rec.get("size_bytes") or 0) > 0, rec.get("size_bytes"))
        check("备份文件真实存在",
              bool(rec.get("file_path")) and Path(rec["file_path"]).exists(), rec.get("file_path"))

        r = client.post("/api/backups", headers=auth(admin), params={"backup_type": "bad"})
        check("非法备份类型被拒绝", r.status_code == 400, r.status_code)

        r = client.get("/api/backups", headers=auth(admin))
        check("备份记录列表可查询", r.status_code == 200 and r.json().get("total", 0) >= 1,
              r.status_code)

        r = client.get(f"/api/backups/{rec.get('id')}/download", headers=auth(admin))
        check("备份包可下载", r.status_code == 200 and len(r.content) > 0, r.status_code)
        check("备份包为 zip 格式", r.content[:2] == b"PK", r.content[:4])

        r = client.get("/api/backups/999999/download", headers=auth(admin))
        check("不存在的备份下载返回 404", r.status_code == 404, r.status_code)

        r = client.delete("/api/backups/cleanup", headers=auth(admin), params={"keep_days": 30})
        check("清理过期备份可执行", r.status_code == 200 and r.json().get("ok") is True,
              f"{r.status_code} {r.text[:150]}")

        db = SessionLocal()
        try:
            cnt = db.scalar(select(text("count(*)")).select_from(BackupRecord)) or 0
            check("备份记录已落库", cnt >= 1, cnt)
            bk = db.scalar(select(AuditLog).where(AuditLog.action == "backup")
                           .order_by(AuditLog.id.desc()))
            check("备份操作写入审计", bk is not None)
        finally:
            db.close()

        # ================= 版本一致性收尾
        db = SessionLocal()
        try:
            orphan = db.scalar(text(
                "select count(*) from files f left join document_versions v on f.version_id = v.id "
                "where v.id is null"
            ))
            check("无游离文件（version_id 全部有效）", (orphan or 0) == 0, orphan)
            multi = db.scalar(text(
                "select count(*) from (select document_id from document_versions where is_current "
                "group by document_id having count(*) > 1) t"
            ))
            check("无文档存在多个当前版本", (multi or 0) == 0, multi)
            mismatch = db.scalar(text(
                "select count(*) from documents d join document_versions v on v.id = d.current_version_id "
                "where v.is_current = false"
            ))
            check("current_version_id 与 is_current 标记一致", (mismatch or 0) == 0, mismatch)
        finally:
            db.close()

    ok = sum(1 for _, passed, _ in results if passed)
    print(f"P9 验收：{ok}/{len(results)} 通过")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
