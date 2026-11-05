"""P8 验收脚本：借阅申请 → 审批 → 临时授权 → 归还 / 续借 / 到期回收。

运行方式（在 backend 目录，使用会话 venv 的 python）：
    python scripts/verify_p8.py
末行输出 "P8 验收：X/Y 通过"。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
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
from app.models.document import Document, DocumentPermission  # noqa: E402
from app.models.enums import BorrowStatus  # noqa: E402
from app.models.room import Room  # noqa: E402
from app.models.workflow import AuditLog, BorrowRequest  # noqa: E402
from app.services import borrow as borrow_service  # noqa: E402

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASS_WORD = "Verify@12345"
ROOM_CODE = "P8T"
results: list[tuple[str, bool, str]] = []

TEXT_SECRET = "秘密级资料正文：地下管廊监测数据与结构安全评估结论。"


def check(name: str, ok: bool, extra: str = "") -> None:
    results.append((name, bool(ok), extra))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  -> ' + str(extra)[:200]) if not ok else ''}", flush=True)


def ensure_user(db, username: str, role: Role, dept_id: int | None) -> None:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(username=username, full_name=f"P8{role.value}", password_hash=pwd.hash(PASS_WORD),
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
        ensure_user(db, "p8_admin", Role.SYSADMIN, dept.id)
        ensure_user(db, "p8_manager", Role.RECORDS_MANAGER, dept.id)
        ensure_user(db, "p8_viewer", Role.VIEWER, dept.id)
        ensure_user(db, "p8_viewer2", Role.VIEWER, dept.id)
        room = db.scalar(select(Room).where(Room.code == ROOM_CODE))
        if room is None:
            room = Room(name="P8验收资料室", code=ROOM_CODE, location="测试位置")
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
           file_name: str, body: str, level: str = "secret") -> dict:
    r = client.post(
        "/api/documents/upload",
        headers=auth(token),
        data={"room_id": room_id, "title": title, "secrecy_level": level},
        files=[("files", (file_name, body.encode("utf-8"), "text/plain"))],
    )
    assert r.status_code == 201, f"上传失败: {r.status_code} {r.text[:300]}"
    return r.json()


def main() -> int:
    room_id = prepare_db()

    with TestClient(app) as client:
        admin = login(client, "p8_admin")
        manager = login(client, "p8_manager")
        viewer = login(client, "p8_viewer")
        viewer2 = login(client, "p8_viewer2")

        d1 = upload(client, admin, room_id, "P8地下管廊监测报告", "p8_secret.txt", TEXT_SECRET, "secret")
        d2 = upload(client, admin, room_id, "P8结构安全评估", "p8_secret2.txt",
                    "秘密级资料：结构安全评估与裂缝处理建议。", "secret")

        # ---------------- 基础可见性
        r = client.get(f"/api/documents/{d1['id']}", headers=auth(viewer))
        check("查阅者未借阅时无法查看秘密级资料", r.status_code == 403, r.status_code)

        # ---------------- 提交申请
        r = client.post("/api/borrow/requests", headers=auth(viewer),
                        json={"document_id": d1["id"], "reason": "参与管廊验收需查阅监测数据", "days": 5})
        check("查阅者可提交借阅申请", r.status_code == 201, f"{r.status_code} {r.text[:150]}")
        req = r.json()
        check("申请单号格式 BR+日期+序号", req["request_no"].startswith("BR") and len(req["request_no"]) == 14,
              req["request_no"])
        check("初始状态为待审批", req["status"] == BorrowStatus.PENDING.value, req["status"])
        check("申请记录期望天数", req["requested_days"] == 5, req["requested_days"])

        r = client.post("/api/borrow/requests", headers=auth(viewer),
                        json={"document_id": d1["id"], "reason": "重复提交测试"})
        check("同一资料在途申请不可重复提交", r.status_code == 409, r.status_code)

        r = client.post("/api/borrow/requests", headers=auth(viewer),
                        json={"document_id": d1["id"], "reason": "x"})
        check("借阅事由过短被拒绝", r.status_code == 422, r.status_code)

        r = client.get("/api/borrow/requests", headers=auth(viewer))
        check("我的借阅列表可查询", r.status_code == 200 and r.json()["total"] >= 1,
              r.status_code)
        r = client.get("/api/borrow/mine", headers=auth(viewer), params={"active_only": True})
        check("借阅中列表此时为空", r.json()["total"] == 0, r.json()["total"])

        # ---------------- 权限边界
        r = client.get("/api/borrow/pending", headers=auth(viewer))
        check("查阅者无权查看待审批列表", r.status_code == 403, r.status_code)
        r = client.post(f"/api/borrow/requests/{req['id']}/approve", headers=auth(viewer), json={})
        check("查阅者无权审批", r.status_code == 403, r.status_code)
        r = client.get(f"/api/borrow/requests/{req['id']}", headers=auth(viewer2))
        check("他人无权查看借阅详情", r.status_code == 403, r.status_code)

        # ---------------- 审批
        r = client.get("/api/borrow/pending", headers=auth(manager))
        check("档案管理员可查看待审批列表", r.status_code == 200 and r.json()["total"] >= 1,
              r.status_code)

        r = client.post(f"/api/borrow/requests/{req['id']}/approve", headers=auth(manager),
                        json={"days": 3, "can_download": True})
        check("审批通过", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
        approved = r.json()
        check("状态变为借阅中", approved["status"] == BorrowStatus.APPROVED.value, approved["status"])
        check("应还时间按批准天数计算",
              approved["due_at"] and approved["remaining_days"] >= 1, approved["remaining_days"])
        check("剩余天数不超过批准天数", approved["remaining_days"] <= 3, approved["remaining_days"])

        r = client.post(f"/api/borrow/requests/{req['id']}/approve", headers=auth(manager), json={})
        check("重复审批被拒绝", r.status_code == 409, r.status_code)

        # ---------------- 授权生效
        r = client.get(f"/api/documents/{d1['id']}", headers=auth(viewer))
        check("借阅通过后可查看秘密级资料", r.status_code == 200, f"{r.status_code} {r.text[:150]}")

        db = SessionLocal()
        try:
            perm = db.scalar(select(DocumentPermission).where(
                DocumentPermission.document_id == d1["id"],
                DocumentPermission.subject_type == "user",
            ))
            check("借阅生成临时授权记录", perm is not None)
            check("临时授权带到期时间", perm is not None and perm.expires_at is not None)
            check("授权按批准开放下载位", perm is not None and perm.can_download is True)
            check("授权未开放打印位", perm is not None and perm.can_print is False)
        finally:
            db.close()

        r = client.get(f"/api/documents/{d1['id']}/files", headers=auth(viewer))
        check("借阅通过后可列出文件", r.status_code == 200 and len(r.json()) >= 1, r.status_code)

        r = client.get(f"/api/documents/{d2['id']}", headers=auth(viewer))
        check("未申请的其他秘密级资料仍不可见", r.status_code == 403, r.status_code)

        # 下载：VIEWER 无角色下载权，但借阅授予了 can_download
        file_id = client.get(f"/api/documents/{d1['id']}/files", headers=auth(viewer)).json()[0]["id"]
        r = client.get(f"/api/files/{file_id}/download", headers=auth(viewer))
        check("借阅授权可下载（越密级）", r.status_code == 200, r.status_code)
        file_id2 = client.get(f"/api/documents/{d2['id']}/files", headers=auth(admin)).json()[0]["id"]
        r = client.get(f"/api/files/{file_id2}/download", headers=auth(viewer))
        check("未授权资料下载仍被拒绝", r.status_code == 403, r.status_code)

        # ---------------- 续借
        r = client.post(f"/api/borrow/requests/{req['id']}/renew", headers=auth(viewer), json={"days": 2})
        check("可续借", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
        check("续借次数累加", r.json()["renew_count"] == 1, r.json()["renew_count"])
        r = client.post(f"/api/borrow/requests/{req['id']}/renew", headers=auth(viewer), json={"days": 2})
        r = client.post(f"/api/borrow/requests/{req['id']}/renew", headers=auth(viewer), json={"days": 2})
        check("续借超过上限被拒绝", r.status_code == 409, r.status_code)

        # ---------------- 驳回路径
        r = client.post("/api/borrow/requests", headers=auth(viewer2),
                        json={"document_id": d2["id"], "reason": "核对结构安全评估结论", "days": 3})
        req2 = r.json()
        r = client.post(f"/api/borrow/requests/{req2['id']}/reject", headers=auth(manager),
                        json={"reason": "资料涉密，请到资料室现场查阅"})
        check("审批驳回成功", r.status_code == 200 and r.json()["status"] == "rejected",
              r.status_code)
        check("驳回记录理由", r.json()["reject_reason"] is not None)
        r = client.get(f"/api/documents/{d2['id']}", headers=auth(viewer2))
        check("驳回后仍不可见", r.status_code == 403, r.status_code)

        # ---------------- 撤回
        r = client.post("/api/borrow/requests", headers=auth(viewer2),
                        json={"document_id": d2["id"], "reason": "补充说明后再申请查阅", "days": 3})
        req3 = r.json()
        r = client.post(f"/api/borrow/requests/{req3['id']}/cancel", headers=auth(viewer2))
        check("申请人可撤回待审批申请", r.status_code == 200 and r.json()["status"] == "cancelled",
              r.status_code)
        r = client.post(f"/api/borrow/requests/{req3['id']}/cancel", headers=auth(viewer2))
        check("已结束申请不可重复撤回", r.status_code == 409, r.status_code)
        r = client.post(f"/api/borrow/requests/{req3['id']}/cancel", headers=auth(viewer))
        check("他人不可撤回我的申请", r.status_code == 403, r.status_code)

        # ---------------- 归还
        r = client.post(f"/api/borrow/requests/{req['id']}/return", headers=auth(viewer))
        check("可提前归还", r.status_code == 200 and r.json()["status"] == "returned", r.status_code)
        r = client.get(f"/api/documents/{d1['id']}", headers=auth(viewer))
        check("归还后权限立即失效", r.status_code == 403, r.status_code)
        db = SessionLocal()
        try:
            left = db.scalar(select(DocumentPermission).where(
                DocumentPermission.document_id == d1["id"],
                DocumentPermission.subject_type == "user",
            ))
            check("归还后授权记录已回收", left is None)
        finally:
            db.close()
        r = client.post(f"/api/borrow/requests/{req['id']}/return", headers=auth(viewer))
        check("重复归还被拒绝", r.status_code == 409, r.status_code)

        # ---------------- 到期回收
        r = client.post("/api/borrow/requests", headers=auth(viewer),
                        json={"document_id": d1["id"], "reason": "到期回收验证", "days": 1})
        req4 = r.json()
        client.post(f"/api/borrow/requests/{req4['id']}/approve", headers=auth(manager), json={"days": 1})
        r = client.get(f"/api/documents/{d1['id']}", headers=auth(viewer))
        check("第二次借阅授权生效", r.status_code == 200, r.status_code)

        # 把到期时间改到过去，模拟时间流逝
        db = SessionLocal()
        try:
            row = db.get(BorrowRequest, req4["id"])
            row.due_at = datetime.now(timezone.utc) - timedelta(hours=1)
            perm = db.scalar(select(DocumentPermission).where(
                DocumentPermission.document_id == d1["id"],
                DocumentPermission.subject_type == "user",
                DocumentPermission.subject_id == row.applicant_id,
            ))
            perm.expires_at = row.due_at
            db.commit()
        finally:
            db.close()

        r = client.post("/api/borrow/sweep", headers=auth(manager))
        body = r.json()
        check("手动触发到期回收成功", r.status_code == 200 and body["expired"] >= 1,
              f"{r.status_code} {body}")
        db = SessionLocal()
        try:
            left = db.scalar(select(DocumentPermission).where(
                DocumentPermission.document_id == d1["id"],
                DocumentPermission.subject_type == "user",
            ))
            check("到期回收同时撤销临时授权", left is None)
            stale = db.scalar(select(text("count(*)")).select_from(DocumentPermission).where(
                DocumentPermission.expires_at.is_not(None),
                DocumentPermission.expires_at <= datetime.now(timezone.utc),
            ))
            check("过期授权残留为 0", (stale or 0) == 0, stale)
        finally:
            db.close()
        r = client.get(f"/api/documents/{d1['id']}", headers=auth(viewer))
        check("到期后查看权限失效", r.status_code == 403, r.status_code)
        r = client.get(f"/api/borrow/requests/{req4['id']}", headers=auth(viewer))
        check("到期记录状态为 expired", r.json()["status"] == "expired", r.json()["status"])

        r = client.get("/api/borrow/sweeper", headers=auth(manager))
        check("回收线程状态可查询", r.status_code == 200 and "alive" in r.json(), r.status_code)
        r = client.get("/api/borrow/sweeper", headers=auth(viewer))
        check("查阅者无权查看回收线程状态", r.status_code == 403, r.status_code)

        # ---------------- 到期后可重新申请
        r = client.post("/api/borrow/requests", headers=auth(viewer),
                        json={"document_id": d1["id"], "reason": "到期后重新申请借阅", "days": 7})
        check("到期后可重新提交申请", r.status_code == 201, f"{r.status_code} {r.text[:150]}")

        # ---------------- 自审批拦截
        r = client.post("/api/borrow/requests", headers=auth(manager),
                        json={"document_id": d1["id"], "reason": "管理员自审批验证", "days": 3})
        own = r.json()
        r = client.post(f"/api/borrow/requests/{own['id']}/approve", headers=auth(manager), json={})
        check("不允许审批自己的申请", r.status_code == 403, r.status_code)

        # ---------------- 审计
        db = SessionLocal()
        try:
            kinds = set(db.scalars(select(AuditLog.action).where(
                AuditLog.action.in_(["borrow_apply", "borrow_approve", "borrow_reject",
                                     "borrow_return", "borrow_renew", "borrow_expire"])
            )).all())
            check("借阅全流程写入审计", len(kinds) >= 5, sorted(kinds))
        finally:
            db.close()

        # ---------------- 分页与筛选
        r = client.get("/api/borrow/requests", headers=auth(manager),
                       params={"mine": "false", "status": "approved", "size": 5})
        body = r.json()
        check("管理员可查看全部借阅并筛选状态", r.status_code == 200, r.status_code)
        check("分页 meta 正确", body["page"] == 1 and body["size"] == 5, body)

        r = client.get("/api/borrow/levels", headers=auth(viewer))
        check("可查询本人可借阅密级范围", r.status_code == 200 and len(r.json()["levels"]) >= 1,
              r.status_code)

    ok = sum(1 for _, passed, _ in results if passed)
    print(f"P8 验收：{ok}/{len(results)} 通过")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
