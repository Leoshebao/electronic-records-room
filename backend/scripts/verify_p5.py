"""P5 验收脚本：资料入库 / 检索 / 版本 / 下载 / 预览 / 权限 / 审计。

运行方式（在 backend 目录）：
    python scripts/verify_p5.py
输出末行为 "P5 验收：X/Y 通过"。
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402
from passlib.context import CryptContext  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Department, Role, User  # noqa: E402
from app.models.room import Room  # noqa: E402

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
PASS_WORD = "Verify@12345"
ROOM_CODE = "P5T"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, extra: str = "") -> None:
    results.append((name, ok, extra))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  -> ' + extra) if extra and not ok else ''}")


def image_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (320, 200), (40, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()


def pdf_bytes() -> bytes:
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )


def ensure_user(db, username: str, role: Role, dept_id: int | None) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        user = User(
            username=username, full_name=f"测试{role.value}",
            password_hash=pwd.hash(PASS_WORD), role=role,
            department_id=dept_id, is_active=True, must_change_password=False,
        )
        db.add(user)
        db.flush()
    else:
        user.password_hash = pwd.hash(PASS_WORD)
        user.must_change_password = False
        user.is_active = True
        user.token_version = 0
    return user


def prepare(db) -> tuple[Room, int]:
    dept = db.scalar(select(Department).where(Department.code == "ZH"))
    if dept is None:
        dept = Department(name="综合部", code="ZH", sort_order=10)
        db.add(dept)
        db.flush()
    ensure_user(db, "p5_admin", Role.SYSADMIN, dept.id)
    ensure_user(db, "p5_manager", Role.RECORDS_MANAGER, dept.id)
    ensure_user(db, "p5_viewer", Role.VIEWER, dept.id)

    room = db.scalar(select(Room).where(Room.code == ROOM_CODE))
    if room is None:
        room = Room(name="P5验收资料室", code=ROOM_CODE, location="测试位置")
        db.add(room)
        db.flush()
    db.commit()
    return room, dept.id


def login(client: TestClient, username: str) -> str:
    r = client.post("/api/auth/login", json={"username": username, "password": PASS_WORD})
    assert r.status_code == 200, f"登录失败 {username}: {r.status_code} {r.text}"
    return r.json()["access_token"]


def main() -> int:
    db = SessionLocal()
    try:
        room, _dept_id = prepare(db)
        room_id = room.id
    finally:
        db.close()

    with TestClient(app) as client:
        # 1 未登录
        r = client.get("/api/documents")
        check("未登录访问资料列表返回 401", r.status_code == 401, str(r.status_code))

        t_admin = login(client, "p5_admin")
        t_mgr = login(client, "p5_manager")
        t_view = login(client, "p5_viewer")
        H = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731

        # 2 单文件上传
        txt = "施工组织设计 第一版 混凝土浇筑方案".encode("utf-8")
        r = client.post(
            "/api/documents/upload",
            headers=H(t_admin),
            data={"room_id": room_id, "title": "施工组织设计（P5验收）",
                  "secrecy_level": "public", "keywords": "施工,方案",
                  "summary": "测试用施工组织设计摘要"},
            files=[("files", ("施组.txt", txt, "text/plain"))],
        )
        ok = r.status_code == 201
        doc1 = r.json() if ok else {}
        check("上传单文件资料成功", ok, r.text[:200])
        check("档号自动生成符合规则", ok and doc1.get("doc_no", "").startswith(f"{ROOM_CODE}-"),
              str(doc1.get("doc_no")))
        check("文件数与体积统计正确",
              ok and doc1.get("file_count") == 1 and doc1.get("total_size") == len(txt),
              f"{doc1.get('file_count')}/{doc1.get('total_size')}")
        check("首个版本为 V1.0 且为当前版本",
              ok and doc1.get("versions") and doc1["versions"][0]["version_label"] == "V1.0"
              and doc1["versions"][0]["is_current"] is True)
        doc1_id = doc1.get("id")

        # 3 多文件上传（图片 + PDF）
        r = client.post(
            "/api/documents/upload",
            headers=H(t_admin),
            data={"room_id": room_id, "title": "现场照片与图纸（P5验收）",
                  "secrecy_level": "internal"},
            files=[("files", ("现场.png", image_bytes(), "image/png")),
                   ("files", ("图纸.pdf", pdf_bytes(), "application/pdf"))],
        )
        ok_multi = r.status_code == 201
        doc2 = r.json() if ok_multi else {}
        check("一次上传多个文件（图片+PDF）", ok_multi and doc2.get("file_count") == 2, r.text[:200])
        doc2_id = doc2.get("id")

        # 4 重复档号
        r = client.post(
            "/api/documents/upload",
            headers=H(t_admin),
            data={"room_id": room_id, "title": "重复档号测试", "doc_no": doc1.get("doc_no"),
                  "secrecy_level": "public"},
            files=[("files", ("x.txt", b"dup", "text/plain"))],
        )
        check("重复档号返回 409", r.status_code == 409, str(r.status_code))

        # 5 非法扩展名
        r = client.post(
            "/api/documents/upload",
            headers=H(t_admin),
            data={"room_id": room_id, "title": "非法类型", "secrecy_level": "public"},
            files=[("files", ("bad.exe", b"MZ....", "application/octet-stream"))],
        )
        check("非法文件类型被拒绝 400", r.status_code == 400, str(r.status_code))

        # 6 空文件
        r = client.post(
            "/api/documents/upload",
            headers=H(t_admin),
            data={"room_id": room_id, "title": "空文件", "secrecy_level": "public"},
            files=[("files", ("empty.txt", b"", "text/plain"))],
        )
        check("空文件被拒绝 400", r.status_code == 400, str(r.status_code))

        # 7 越权密级上传
        r = client.post(
            "/api/documents/upload",
            headers=H(t_mgr),
            data={"room_id": room_id, "title": "机密资料越权上传", "secrecy_level": "confidential"},
            files=[("files", ("secret.txt", b"secret", "text/plain"))],
        )
        check("资料员上传机密级被拒 403", r.status_code == 403, str(r.status_code))

        # 8 上传一份秘密级，供 viewer/manager 权限对比
        r = client.post(
            "/api/documents/upload",
            headers=H(t_admin),
            data={"room_id": room_id, "title": "涉密会议纪要（P5验收）", "secrecy_level": "secret"},
            files=[("files", ("纪要.txt", "秘密内容".encode(), "text/plain"))],
        )
        ok_secret = r.status_code == 201
        doc3_id = r.json().get("id") if ok_secret else None
        check("管理员上传秘密级资料", ok_secret, r.text[:200])

        # 9 关键词检索
        r = client.get("/api/documents", headers=H(t_admin), params={"keyword": "施工组织设计"})
        items = r.json().get("items", []) if r.status_code == 200 else []
        check("按关键词检索命中", r.status_code == 200 and any(i["id"] == doc1_id for i in items),
              f"{r.status_code}/{len(items)}")

        # 10 分页元信息
        meta = r.json().get("meta", {}) if r.status_code == 200 else {}
        check("分页 meta 完整", all(k in meta for k in ("total", "page", "size", "pages")), str(meta))

        # 11 viewer 看不到秘密级
        r = client.get("/api/documents", headers=H(t_view), params={"room_id": room_id})
        vids = [i["id"] for i in r.json().get("items", [])] if r.status_code == 200 else []
        check("查阅者列表不含秘密级资料", r.status_code == 200 and doc3_id not in vids,
              f"{r.status_code}/{vids}")

        # 12 viewer 详情取秘密级 -> 403
        r = client.get(f"/api/documents/{doc3_id}", headers=H(t_view))
        check("查阅者访问秘密级详情 403", r.status_code == 403, str(r.status_code))

        # 13 详情浏览量递增
        r1 = client.get(f"/api/documents/{doc1_id}", headers=H(t_admin))
        r2 = client.get(f"/api/documents/{doc1_id}", headers=H(t_admin))
        check("详情浏览量递增",
              r1.status_code == 200 and r2.json()["view_count"] > r1.json()["view_count"])

        # 14 修改元数据
        r = client.patch(f"/api/documents/{doc1_id}", headers=H(t_mgr),
                         json={"title": "施工组织设计（P5验收-修订）", "change_note": "标题规范化"})
        check("修改题名成功且版本备注更新",
              r.status_code == 200 and "修订" in r.json()["title"]
              and "标题规范化" in (r.json()["versions"][0]["change_note"] or ""), r.text[:200])

        # 15 新增版本
        r = client.post(f"/api/documents/{doc1_id}/versions", headers=H(t_mgr),
                        data={"change_note": "补充第二版方案"},
                        files=[("files", ("施组V2.txt", "施工组织设计 第二版".encode(), "text/plain"))])
        ver_ok = r.status_code == 201
        versions = r.json()["versions"] if ver_ok else []
        check("新增版本成功且版本号递增",
              ver_ok and versions[0]["version_label"] == "V2.0"
              and sum(1 for v in versions if v["is_current"]) == 1, r.text[:200])
        check("新版本文档文件数累加", ver_ok and r.json()["file_count"] == 2)

        # 16 viewer 无下载权限
        fid = doc1["files"][0]["id"] if doc1.get("files") else None
        r = client.get(f"/api/files/{fid}/download", headers=H(t_view))
        check("查阅者下载被拒 403", r.status_code == 403, str(r.status_code))

        # 17 下载成功 + 下载次数
        r = client.get(f"/api/files/{fid}/download", headers=H(t_mgr))
        ok_dl = r.status_code == 200 and r.content == txt
        check("下载内容与原件一致", ok_dl, f"{r.status_code}/{len(r.content)}")
        check("下载响应带安全头",
              "attachment" in (r.headers.get("content-disposition") or "")
              and "filename*=UTF-8''" in (r.headers.get("content-disposition") or ""),
              r.headers.get("content-disposition", ""))
        d = client.get(f"/api/documents/{doc1_id}", headers=H(t_admin)).json()
        check("下载次数已累计", d.get("download_count", 0) >= 1, str(d.get("download_count")))

        # 18 Range 分段请求
        r = client.get(f"/api/files/{fid}/download", headers={**H(t_mgr), "Range": "bytes=0-9"})
        check("Range 请求返回 206 与分段内容",
              r.status_code == 206 and len(r.content) == 10
              and r.headers.get("content-range", "").startswith("bytes 0-9/"), str(r.status_code))

        # 19 预览 inline
        pdf_fid = doc2["files"][1]["id"] if doc2.get("files") else None
        r = client.get(f"/api/files/{pdf_fid}/preview", headers=H(t_view))
        check("预览 PDF 为内联展示且允许查阅者",
              r.status_code == 200 and "inline" in (r.headers.get("content-disposition") or ""),
              str(r.status_code))

        # 20 缩略图
        img_fid = doc2["files"][0]["id"] if doc2.get("files") else None
        r = client.get(f"/api/files/{img_fid}/thumb", headers=H(t_view), params={"size": 120})
        check("图片缩略图生成 JPEG", r.status_code == 200 and r.headers.get("content-type") == "image/jpeg"
              and len(r.content) > 100, f"{r.status_code}/{len(r.content)}")

        # 21 软删除
        r = client.delete(f"/api/documents/{doc2_id}", headers=H(t_mgr))
        r2 = client.get(f"/api/documents/{doc2_id}", headers=H(t_admin))
        r3 = client.get("/api/documents", headers=H(t_admin), params={"room_id": room_id})
        check("软删除后详情 404、列表不再出现",
              r.status_code == 200 and r2.status_code == 404
              and doc2_id not in [i["id"] for i in r3.json().get("items", [])],
              f"{r.status_code}/{r2.status_code}")

        # 22 审计落库
        with SessionLocal() as s:
            rows = s.execute(text(
                "select action, count(*) from audit_logs where action in "
                "('doc_create','doc_download','doc_view','doc_delete') group by action"
            )).all()
        acts = {a: c for a, c in rows}
        check("关键操作均已写入审计",
              all(acts.get(k, 0) > 0 for k in ("doc_create", "doc_download", "doc_view", "doc_delete")),
              str(acts))

        # 23 路径穿越防护
        from fastapi import HTTPException

        from app.services import storage

        blocked = False
        try:
            storage.resolve_safe("../../../../windows/win.ini")
        except HTTPException:
            blocked = True
        check("越界路径被拦截", blocked)

        # 24 存储用量（仅管理员）
        r = client.get("/api/documents/storage/usage", headers=H(t_admin))
        r2 = client.get("/api/documents/storage/usage", headers=H(t_mgr))
        check("存储用量接口仅系统管理员可用",
              r.status_code == 200 and r2.status_code == 403
              and r.json().get("file_count", 0) > 0, f"{r.status_code}/{r2.status_code}")

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\nP5 验收：{passed}/{total} 通过")
    if passed != total:
        print("失败项：")
        for name, ok, extra in results:
            if not ok:
                print(f"  - {name}  {extra}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
