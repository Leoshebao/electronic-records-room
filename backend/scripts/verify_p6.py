"""P6 验收脚本：OCR 异步队列 / 文本提取 / 状态流转 / 检索联动 / 审计。

运行方式（在 backend 目录，使用会话 venv 的 python）：
    python scripts/verify_p6.py
末行输出 "P6 验收：X/Y 通过"。

说明：本机未安装 PaddleOCR（离线模型体积大），真实扫描件会走 skipped 分支；
脚本用桩函数覆盖 OCR 引擎，验证"引擎可用时"的状态流转代码路径。
"""
from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

# 关闭后台线程自动启动，避免与断言时序互相干扰；需要时在用例中显式启停
os.environ["OCR_WORKER_ENABLED"] = "false"
os.environ["OCR_ENABLED"] = "true"

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient  # noqa: E402
from passlib.context import CryptContext  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Department, Role, User  # noqa: E402
from app.models.document import Document, FileObject  # noqa: E402
from app.models.enums import AuditAction, OCRStatus  # noqa: E402
from app.models.room import Room  # noqa: E402
from app.models.workflow import OCRTask  # noqa: E402
from app.services import ocr, ocr_worker  # noqa: E402

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASS_WORD = "Verify@12345"
ROOM_CODE = "P6T"
TMP = settings.storage_path / "_verify_p6"
REL_TMP = "_verify_p6"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    results.append((name, bool(ok), extra))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  -> ' + str(extra)[:160]) if not ok else ''}", flush=True)


def ensure_user(db, username: str, role: Role, dept_id: int | None) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(username=username, full_name=f"P6{role.value}",
                    password_hash=pwd.hash(PASS_WORD), role=role, department_id=dept_id,
                    is_active=True, must_change_password=False)
        db.add(user)
        db.flush()
    else:
        user.password_hash = pwd.hash(PASS_WORD)
        user.must_change_password = False
        user.is_active = True
        user.token_version = 0
    return user


def prepare_db() -> int:
    db = SessionLocal()
    try:
        dept = db.scalar(select(Department).where(Department.code == "ZH"))
        if dept is None:
            dept = Department(name="综合部", code="ZH", sort_order=10)
            db.add(dept)
            db.flush()
        ensure_user(db, "p6_admin", Role.SYSADMIN, dept.id)
        ensure_user(db, "p6_manager", Role.RECORDS_MANAGER, dept.id)
        ensure_user(db, "p6_viewer", Role.VIEWER, dept.id)
        room = db.scalar(select(Room).where(Room.code == ROOM_CODE))
        if room is None:
            room = Room(name="P6验收资料室", code=ROOM_CODE, location="测试位置")
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


def make_docx(text_content: str) -> bytes:
    from docx import Document as Docx

    doc = Docx()
    doc.add_paragraph(text_content)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def make_xlsx(cell: str) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    wb.active["A1"] = cell
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def make_pptx(slide_text: str) -> bytes:
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    box = slide.shapes.add_textbox(Inches(1), Inches(1), Inches(4), Inches(1))
    box.text_frame.text = slide_text
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def make_image() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (400, 240), (230, 230, 230)).save(buf, format="PNG")
    return buf.getvalue()


def make_blank_pdf() -> bytes:
    """有页面但无文本层的 PDF（模拟扫描件）。"""
    import fitz

    doc = fitz.open()
    doc.new_page(width=300, height=300)
    data = doc.tobytes()
    doc.close()
    return data


def upload(client: TestClient, token: str, room_id: int, title: str,
           file_name: str, content: bytes, mime: str = "text/plain",
           level: str = "internal") -> dict:
    r = client.post(
        "/api/documents/upload",
        headers={"Authorization": f"Bearer {token}"},
        data={"room_id": room_id, "title": title, "secrecy_level": level},
        files=[("files", (file_name, content, mime))],
    )
    assert r.status_code == 201, f"上传失败: {r.status_code} {r.text[:300]}"
    return r.json()


def get_file(db, file_id: int) -> FileObject | None:
    return db.get(FileObject, file_id)


def task_count(db, file_id: int) -> int:
    return db.scalar(select(text("count(*)")).select_from(OCRTask).where(OCRTask.file_id == file_id)) or 0


def latest_task(db, file_id: int) -> OCRTask | None:
    return db.scalars(
        select(OCRTask).where(OCRTask.file_id == file_id).order_by(OCRTask.id.desc())
    ).first()


def main() -> int:
    room_id = prepare_db()
    TMP.mkdir(parents=True, exist_ok=True)

    with TestClient(app) as client:
        # ---------- 1. 权限 ----------
        r = client.get("/api/ocr/stats")
        check("未登录访问 OCR 统计返回 401", r.status_code == 401, r.status_code)

        t_admin = login(client, "p6_admin")
        t_mgr = login(client, "p6_manager")
        t_view = login(client, "p6_viewer")
        HA = {"Authorization": f"Bearer {t_admin}"}
        HM = {"Authorization": f"Bearer {t_mgr}"}
        HV = {"Authorization": f"Bearer {t_view}"}

        r = client.get("/api/ocr/stats", headers=HV)
        check("查阅者访问 OCR 统计被拒绝 403", r.status_code == 403, r.status_code)
        r = client.get("/api/ocr/stats", headers=HM)
        body = r.json() if r.status_code == 200 else {}
        check("档案管理员可查看 OCR 统计", r.status_code == 200 and {"tasks", "files", "pending"} <= set(body),
              r.text[:200])
        r = client.get("/api/ocr/engine", headers=HM)
        ek = r.json() if r.status_code == 200 else {}
        check("引擎自检返回可用性与运行参数",
              r.status_code == 200 and {"available", "engine", "enabled", "worker_enabled"} <= set(ek),
              r.text[:200])

        # ---------- 2. 上传入队 ----------
        db = SessionLocal()
        try:
            doc1 = upload(client, t_mgr, room_id, "P6文本资料", "P6正文.txt",
                          "本工程混凝土浇筑方案采用分层连续浇筑工艺，坍落度控制在 180mm。".encode("utf-8"))
            file1 = doc1["files"][0]
            check("上传后文件 OCR 状态为 queued", file1["ocr_status"] == "queued", file1["ocr_status"])
            check("上传后生成排队任务", latest_task(db, file1["id"]) is not None)
            check("文件表 ocr_status 与队列一致",
                  get_file(db, file1["id"]).ocr_status == OCRStatus.QUEUED,
                  get_file(db, file1["id"]).ocr_status)
        finally:
            db.close()

        r = client.get("/api/ocr/tasks", params={"status": "queued", "size": 100}, headers=HM)
        body = r.json() if r.status_code == 200 else {}
        ids = [it["file_id"] for it in body.get("items", [])]
        check("任务列表可按状态过滤", r.status_code == 200 and file1["id"] in ids, r.text[:200])
        check("任务列表分页元信息完整",
              set(body.get("meta", {})) == {"total", "page", "size", "pages"}, body.get("meta"))
        r = client.get("/api/ocr/tasks", params={"status": "bogus"}, headers=HM)
        check("非法状态过滤返回 400", r.status_code == 400, r.status_code)

        # ---------- 3. 幂等 ----------
        db = SessionLocal()
        try:
            before = task_count(db, file1["id"])
            ocr_worker.enqueue_file(db, get_file(db, file1["id"]))
            ocr_worker.enqueue_file(db, get_file(db, file1["id"]))
            db.commit()
            after = task_count(db, file1["id"])
            check("同一文件重复入队不产生重复任务", before == after == 1, f"{before}->{after}")
        finally:
            db.close()

        # ---------- 4. 队列处理 ----------
        r = client.post("/api/ocr/drain", params={"limit": 10}, headers=HV)
        check("查阅者无权触发队列处理 403", r.status_code == 403, r.status_code)
        r = client.post("/api/ocr/drain", params={"limit": 20}, headers=HM)
        drained = r.json() if r.status_code == 200 else {}
        check("管理员跑队列返回处理数", r.status_code == 200 and drained.get("processed", 0) >= 1, r.text[:200])

        db = SessionLocal()
        try:
            task = latest_task(db, file1["id"])
            fobj = get_file(db, file1["id"])
            check("任务状态流转到 ready", task.status == OCRStatus.READY, task.status)
            check("文件 OCR 状态流转到 ready", fobj.ocr_status == OCRStatus.READY, fobj.ocr_status)
            check("文本层内容被完整提取",
                  "混凝土浇筑方案" in (fobj.ocr_text or ""), (fobj.ocr_text or "")[:60])
            check("解析耗时已记录", (task.duration_ms or 0) >= 0 and task.finished_at is not None,
                  f"{task.duration_ms}")
        finally:
            db.close()

        # ---------- 5. 检索联动 ----------
        r = client.get("/api/documents", params={"keyword": "坍落度"}, headers=HM)
        body = r.json() if r.status_code == 200 else {}
        hits = body.get("items", [])
        check("正文关键词可检索到资料（OCR 全文参与检索）",
              any(h["id"] == doc1["id"] for h in hits),
              f"status={r.status_code} total={body.get('meta', {}).get('total')} {r.text[:120]}")
        r = client.get("/api/documents", params={"keyword": "绝不存在的关键词ZZZ"}, headers=HM)
        total_none = r.json().get("meta", {}).get("total") if r.status_code == 200 else None
        check("无关关键词不误命中", total_none == 0, f"status={r.status_code} total={total_none}")

        # ---------- 6. 扫描件在无引擎时的降级 ----------
        img_doc = upload(client, t_mgr, room_id, "P6扫描图片", "P6扫描.png", make_image(), "image/png")
        img_file = img_doc["files"][0]
        client.post("/api/ocr/drain", params={"limit": 20}, headers=HM)
        db = SessionLocal()
        try:
            fimg = get_file(db, img_file["id"])
            timg = latest_task(db, img_file["id"])
            if ocr.ocr_engine_status().get("available"):
                check("图片经 OCR 解析为 ready", fimg.ocr_status == OCRStatus.READY, fimg.ocr_status)
            else:
                check("无 OCR 引擎时图片标记 skipped 而非失败",
                      fimg.ocr_status == OCRStatus.SKIPPED and timg.status == OCRStatus.SKIPPED,
                      f"{fimg.ocr_status}/{timg.status}")
                check("跳过任务不进入重试循环", (timg.retry_count or 0) == 0, timg.retry_count)
        finally:
            db.close()

        pdf_doc = upload(client, t_mgr, room_id, "P6扫描PDF", "P6扫描.pdf",
                         make_blank_pdf(), "application/pdf")
        pdf_file = pdf_doc["files"][0]
        client.post("/api/ocr/drain", params={"limit": 20}, headers=HM)
        db = SessionLocal()
        try:
            fpdf = get_file(db, pdf_file["id"])
            tpdf = latest_task(db, pdf_file["id"])
            expect = OCRStatus.READY if ocr.ocr_engine_status().get("available") else OCRStatus.SKIPPED
            check("无文本层 PDF 按引擎可用性降级", fpdf.ocr_status == expect,
                  f"{fpdf.ocr_status}/{tpdf.status}")
        finally:
            db.close()

        # ---------- 7. 多格式文本提取 ----------
        docx_path = TMP / "p6.docx"
        docx_path.write_bytes(make_docx("附件三 竣工验收记录 编号 JZ-2026-001"))
        r = ocr.extract_text(f"{REL_TMP}/p6.docx", "docx")
        check("DOCX 文本提取成功", r.ok and "竣工验收记录" in r.text, r.error or r.text[:40])

        xlsx_path = TMP / "p6.xlsx"
        xlsx_path.write_bytes(make_xlsx("材料进场台账"))
        r = ocr.extract_text(f"{REL_TMP}/p6.xlsx", "xlsx")
        check("XLSX 文本提取成功", r.ok and "材料进场台账" in r.text, r.error or r.text[:40])

        pptx_path = TMP / "p6.pptx"
        pptx_path.write_bytes(make_pptx("安全生产月度汇报"))
        r = ocr.extract_text(f"{REL_TMP}/p6.pptx", "pptx")
        check("PPTX 文本提取成功", r.ok and "安全生产" in r.text, r.error or r.text[:40])

        # ---------- 8. 引擎可用路径（桩替换识别函数） ----------
        class _FakeEngine:
            pass

        original_get_engine = ocr.get_ocr_engine
        original_ocr_bytes = ocr.ocr_image_bytes
        try:
            ocr.get_ocr_engine = lambda: _FakeEngine()  # type: ignore[assignment]
            ocr.ocr_image_bytes = lambda data: "扫描件识别文本：施工许可证"  # type: ignore[assignment]
            img_path = TMP / "p6_stub.png"
            img_path.write_bytes(make_image())
            r = ocr.extract_text(f"{REL_TMP}/p6_stub.png", "png")
            check("引擎可用时图片走 OCR 路径", r.method == "ocr" and "施工许可证" in r.text,
                  f"{r.method}/{r.text[:20]}")
        finally:
            ocr.get_ocr_engine = original_get_engine  # type: ignore[assignment]
            ocr.ocr_image_bytes = original_ocr_bytes  # type: ignore[assignment]

        # ---------- 9. 长度上限保护 ----------
        long_path = TMP / "p6_long.txt"
        long_path.write_text("长文本" * 500, encoding="utf-8")
        old_limit = settings.OCR_MAX_CHARS
        try:
            settings.OCR_MAX_CHARS = 50
            r = ocr.extract_text(f"{REL_TMP}/p6_long.txt", "txt")
            check("超长文本按 OCR_MAX_CHARS 截断", len(r.text) <= 50, len(r.text))
        finally:
            settings.OCR_MAX_CHARS = old_limit

        # ---------- 10. 重排 / 重试 / 超时回收 ----------
        r = client.post(f"/api/ocr/documents/{doc1['id']}/reocr", headers=HV)
        check("查阅者无权重排解析 403", r.status_code == 403, r.status_code)
        r = client.post(f"/api/ocr/documents/{doc1['id']}/reocr",
                        params={"run_now": "true"}, headers=HM)
        body = r.json() if r.status_code == 200 else {}
        check("整份资料可重新解析", r.status_code == 200 and body.get("created", 0) >= 1, r.text[:200])
        db = SessionLocal()
        try:
            check("重排后文件恢复 ready", get_file(db, file1["id"]).ocr_status == OCRStatus.READY,
                  get_file(db, file1["id"]).ocr_status)
        finally:
            db.close()

        r = client.post(f"/api/ocr/files/{file1['id']}/retry", headers=HM)
        check("单文件可手动重试排队", r.status_code == 200 and r.json().get("created") == 1, r.text[:200])
        client.post("/api/ocr/drain", params={"limit": 20}, headers=HM)

        db = SessionLocal()
        try:
            stuck = latest_task(db, file1["id"])
            stuck.status = OCRStatus.PROCESSING
            from datetime import datetime, timedelta, timezone
            stuck.started_at = datetime.now(timezone.utc) - timedelta(
                minutes=settings.OCR_TASK_TIMEOUT_MINUTES + 5)
            db.commit()
            recovered = ocr_worker.reset_stuck_tasks(db)
            db.refresh(stuck)
            check("超时任务被回收为排队", recovered >= 1 and stuck.status == OCRStatus.QUEUED,
                  f"{recovered}/{stuck.status}")
            ocr_worker.drain(db, limit=20)
        finally:
            db.close()

        # ---------- 11. 审计 ----------
        db = SessionLocal()
        try:
            rows = db.execute(
                text("select count(*) from audit_logs where action = :a"),
                {"a": AuditAction.OCR_PROCESS.value},
            ).scalar()
            check("解析动作写入审计日志", (rows or 0) >= 2, rows)
        finally:
            db.close()

        # ---------- 12. 后台线程 ----------
        r = client.post("/api/ocr/worker/start", headers=HV)
        check("查阅者无权启停解析线程 403", r.status_code == 403, r.status_code)
        r = client.post("/api/ocr/worker/start", headers=HA)
        check("管理员可启动解析线程", r.status_code == 200 and r.json().get("worker_alive") is True,
              r.text[:200])

        auto_doc = upload(client, t_mgr, room_id, "P6线程自动解析", "P6线程.txt",
                          "后台线程自动抽取的运维值班记录".encode("utf-8"))
        auto_file = auto_doc["files"][0]
        deadline = time.time() + 20
        status_seen = ""
        while time.time() < deadline:
            db = SessionLocal()
            try:
                status_seen = str(get_file(db, auto_file["id"]).ocr_status)
            finally:
                db.close()
            if status_seen == OCRStatus.READY.value:
                break
            time.sleep(1)
        check("后台线程自动完成解析（无需手动触发）", status_seen == "ready", status_seen)

        r = client.post("/api/ocr/worker/stop", headers=HA)
        check("管理员可停止解析线程", r.status_code == 200 and r.json().get("worker_alive") is False,
              r.text[:200])

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\nP6 验收：{passed}/{total} 通过", flush=True)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
