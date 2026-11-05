"""OCR 命令行工具：不启动 Web 服务也能补跑解析。

用法（在 backend 目录下）：
    python scripts/ocr_cli.py stats        # 查看队列与文件解析状态
    python scripts/ocr_cli.py drain        # 跑空队列（可加 --limit 500）
    python scripts/ocr_cli.py requeue      # 全库重新排队后跑空（谨慎，耗时）
    python scripts/ocr_cli.py engine       # 检查 OCR 引擎可用性

适用场景：服务器夜间批处理、历史存量资料首次建档后的批量补跑。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.document import FileObject  # noqa: E402
from app.models.enums import OCRStatus  # noqa: E402
from app.models.workflow import OCRTask  # noqa: E402
from app.services import ocr, ocr_worker  # noqa: E402


def cmd_engine() -> int:
    info = ocr.ocr_engine_status()
    print("OCR 引擎状态：")
    for key, value in info.items():
        print(f"  {key}: {value}")
    return 0


def cmd_stats() -> int:
    with SessionLocal() as db:
        tasks = dict(
            db.execute(select(OCRTask.status, func.count(OCRTask.id)).group_by(OCRTask.status)).all()
        )
        files = dict(
            db.execute(
                select(FileObject.ocr_status, func.count(FileObject.id))
                .where(FileObject.status == "stored")
                .group_by(FileObject.ocr_status)
            ).all()
        )
    print("任务表：", {str(k): v for k, v in tasks.items()} or "空")
    print("文件表：", {str(k): v for k, v in files.items()} or "空")
    pending = sum(v for k, v in tasks.items() if k in (OCRStatus.QUEUED, OCRStatus.PROCESSING))
    print("待处理：", pending)
    return 0


def cmd_drain(limit: int) -> int:
    with SessionLocal() as db:
        created = ocr_worker.backfill_queue(db)
        if created:
            print(f"补建遗漏任务 {created} 条")
        processed = ocr_worker.drain(db, limit=limit)
    print(f"本次处理 {processed} 条任务")
    return 0


def cmd_requeue(limit: int) -> int:
    with SessionLocal() as db:
        rows = db.scalars(
            select(FileObject).where(FileObject.status == "stored")
        ).all()
        for file_obj in rows:
            file_obj.ocr_status = OCRStatus.QUEUED
            file_obj.ocr_text = None
        db.commit()
        print(f"已重置 {len(rows)} 个文件的解析状态")
        processed = ocr_worker.drain(db, limit=limit)
    print(f"本次处理 {processed} 条任务")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="电子资料室 OCR 命令行工具")
    parser.add_argument(
        "command", choices=["stats", "drain", "requeue", "engine"], help="要执行的子命令"
    )
    parser.add_argument("--limit", type=int, default=200, help="单次最多处理任务数")
    args = parser.parse_args()

    if args.command == "engine":
        return cmd_engine()
    if args.command == "stats":
        return cmd_stats()
    if args.command == "drain":
        return cmd_drain(args.limit)
    return cmd_requeue(args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
