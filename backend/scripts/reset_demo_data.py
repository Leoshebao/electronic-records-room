"""清理试用/验收测试残留数据，只保留综合档案室与三级示例类目。

保留：用户、部门、角色，综合档案室（ZH）及其全部类目
清除：其余资料室及下属资料、版本、物理文件、OCR 任务、借阅申请、细粒度授权
说明：审计日志受数据库触发器（prevent_audit_modify）保护，不可删除，脚本自动保留，
      如需彻底清空审计记录只能重建数据库。

用法（在 backend 目录下执行）：
    python scripts/reset_demo_data.py               # 预演，仅输出待删范围，不落库
    python scripts/reset_demo_data.py --apply       # 执行清理
    python scripts/reset_demo_data.py --apply --purge-files   # 同时把孤儿物理文件移入回收目录
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.core.config import settings  # noqa: E402

KEEP_ROOM_CODE = "ZH"
RECYCLE_DIR = Path("storage_recycled")   # 相对 backend 目录


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正执行删除；缺省为预演")
    ap.add_argument("--purge-files", action="store_true",
                    help="把 storage 下不再被数据库引用的物理文件移入回收目录")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        rooms = db.execute(text(
            "select id, code, name from rooms where code <> :keep order by id"),
            {"keep": KEEP_ROOM_CODE}).all()
        room_ids = [r[0] for r in rooms]
        print("待删除资料室：")
        for r in rooms:
            print(f"  - {r[2]}（{r[1]}，id={r[0]}）")

        doc_ids, rel_paths = [], []
        if room_ids:
            doc_ids = [r[0] for r in db.execute(text(
                "select id from documents where room_id = any(:ids)"),
                {"ids": room_ids}).all()]
            if doc_ids:
                rel_paths = [r[0] for r in db.execute(text(
                    "select rel_path from files where document_id = any(:ids)"),
                    {"ids": doc_ids}).all()]

        print(f"待删除资料：{len(doc_ids)} 份，物理文件：{len(rel_paths)} 个")

        if not args.apply:
            print("\n[预演] 未做任何修改。确认无误后加 --apply 执行。")
            return 0

        with db.begin():
            if doc_ids:
                db.execute(text("update documents set current_version_id = null "
                                "where id = any(:ids)"), {"ids": doc_ids})
                db.execute(text("delete from ocr_tasks where file_id in "
                                "(select id from files where document_id = any(:ids))"),
                           {"ids": doc_ids})
                db.execute(text("delete from borrow_requests where document_id = any(:ids)"),
                           {"ids": doc_ids})
                db.execute(text("delete from document_permissions where document_id = any(:ids)"),
                           {"ids": doc_ids})
                db.execute(text("delete from document_tags where document_id = any(:ids)"),
                           {"ids": doc_ids})
                db.execute(text("delete from document_versions where document_id = any(:ids)"),
                           {"ids": doc_ids})
                db.execute(text("delete from files where document_id = any(:ids)"),
                           {"ids": doc_ids})
                db.execute(text("delete from documents where id = any(:ids)"),
                           {"ids": doc_ids})
            if room_ids:
                db.execute(text("delete from categories where room_id = any(:ids) "
                                "and parent_id is not null"), {"ids": room_ids})
                db.execute(text("delete from categories where room_id = any(:ids)"),
                           {"ids": room_ids})
                db.execute(text("delete from rooms where id = any(:ids)"),
                           {"ids": room_ids})
        print("\n[完成] 业务数据已清理，审计日志按设计保留。")
    finally:
        db.close()

    if args.purge_files:
        storage = Path(settings.STORAGE_ROOT)
        if not storage.is_absolute():
            # 后端以项目根目录为工作目录运行，脚本在 backend 下执行，需回溯一级
            storage = Path(__file__).resolve().parents[2] / storage
        root = storage.resolve()
        recycle = (Path(__file__).resolve().parents[1] / RECYCLE_DIR).resolve()
        recycle.mkdir(parents=True, exist_ok=True)
        kept = {Path(p).as_posix() for p in rel_paths}
        moved = 0
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if rel in kept:
                continue          # 仍被引用或已随记录删除，交由人工确认
            target = recycle / rel.replace("/", "_")
            shutil.move(str(path), str(target))
            moved += 1
        print(f"[完成] 孤儿物理文件 {moved} 个已移入 {recycle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
