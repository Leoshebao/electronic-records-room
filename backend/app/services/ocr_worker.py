"""OCR 异步队列 worker。

设计：数据库任务表 + 单线程轮询（10~30 人规模不需要 Redis/Celery）。
可靠性：
- 认领任务用 SELECT ... FOR UPDATE SKIP LOCKED，多进程部署也不会重复处理；
- 处理耗时的解析动作放在事务外，避免长事务锁表；
- 启动时把超过超时阈值的 processing 任务回收成 queued（进程崩溃自愈）；
- 解析失败按 OCR_MAX_RETRY 重试，超过后置 failed 并保留错误信息。
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.document import Document, FileObject
from app.models.enums import AuditAction, OCRStatus
from app.models.workflow import OCRTask
from app.services import ocr
from app.services.audit import write_audit
from app.services.documents import refresh_search_text

logger = logging.getLogger("erecords.ocr_worker")

_stop = threading.Event()
_thread: threading.Thread | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- 入队
def enqueue_file(db: Session, file_obj: FileObject) -> OCRTask | None:
    """为单个文件建任务。已存在未完成任务时不重复建。"""
    exists = db.scalar(
        select(func.count(OCRTask.id)).where(
            OCRTask.file_id == file_obj.id,
            OCRTask.status.in_([OCRStatus.QUEUED, OCRStatus.PROCESSING]),
        )
    )
    if exists:
        return None
    task = OCRTask(file_id=file_obj.id, status=OCRStatus.QUEUED, engine=settings.OCR_ENGINE)
    db.add(task)
    file_obj.ocr_status = OCRStatus.QUEUED
    db.flush()
    return task


def enqueue_document(db: Session, doc: Document, only_missing: bool = True) -> int:
    """为一份资料的落盘文件批量入队，返回新建任务数。"""
    stmt = select(FileObject).where(
        FileObject.document_id == doc.id, FileObject.status == "stored"
    )
    if only_missing:
        stmt = stmt.where(FileObject.ocr_status.in_([OCRStatus.QUEUED, OCRStatus.FAILED]))
    created = 0
    for file_obj in db.scalars(stmt).all():
        if enqueue_file(db, file_obj) is not None:
            created += 1
    return created


def backfill_queue(db: Session) -> int:
    """启动自愈：把 queued 但没有任务记录的文件补建任务。"""
    rows = db.scalars(
        select(FileObject).where(
            FileObject.status == "stored", FileObject.ocr_status == OCRStatus.QUEUED
        )
    ).all()
    created = 0
    for file_obj in rows:
        if enqueue_file(db, file_obj) is not None:
            created += 1
    if created:
        db.commit()
        logger.info("补建 OCR 任务 %d 条", created)
    return created


def reset_stuck_tasks(db: Session) -> int:
    """把长时间停留在 processing 的任务回收为 queued。"""
    deadline = _now() - timedelta(minutes=settings.OCR_TASK_TIMEOUT_MINUTES)
    result = db.execute(
        update(OCRTask)
        .where(OCRTask.status == OCRStatus.PROCESSING, OCRTask.started_at < deadline)
        .values(status=OCRStatus.QUEUED, started_at=None,
                error_msg="任务超时已自动回收")
    )
    db.commit()
    count = result.rowcount or 0
    if count:
        logger.warning("回收超时 OCR 任务 %d 条", count)
    return count


# ---------------------------------------------------------------- 处理
def _claim(db: Session) -> OCRTask | None:
    task = db.scalars(
        select(OCRTask)
        .where(OCRTask.status == OCRStatus.QUEUED)
        .order_by(OCRTask.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    ).first()
    if task is None:
        return None
    task.status = OCRStatus.PROCESSING
    task.started_at = _now()
    db.commit()
    db.refresh(task)
    return task


def _finish(
    db: Session,
    task: OCRTask,
    *,
    status: OCRStatus,
    text: str | None = None,
    pages: int = 0,
    error: str | None = None,
) -> None:
    file_obj = db.get(FileObject, task.file_id)
    if file_obj is not None:
        file_obj.ocr_status = status
        if status == OCRStatus.READY:
            file_obj.ocr_text = text or None
            if pages:
                file_obj.page_count = pages
    task.status = status
    task.error_msg = error
    task.finished_at = _now()
    if task.started_at:
        task.duration_ms = int((task.finished_at - task.started_at).total_seconds() * 1000)

    # 同步刷新型检索文本，让新入库资料立刻可被全文命中
    if status == OCRStatus.READY and file_obj is not None:
        document = db.get(Document, file_obj.document_id)
        if document is not None:
            refresh_search_text(db, document)
    db.commit()


def process_once(db: Session) -> bool:
    """处理一条排队任务。返回是否实际处理了任务。"""
    task = _claim(db)
    if task is None:
        return False

    file_obj = db.get(FileObject, task.file_id)
    if file_obj is None or file_obj.status == "deleted":
        _finish(db, task, status=OCRStatus.SKIPPED, error="文件记录不存在或已删除")
        return True

    try:
        result = ocr.extract_text(file_obj.rel_path, file_obj.ext)
    except Exception as exc:  # noqa: BLE001  兜底，防止单个坏文件拖死 worker
        logger.exception("OCR 处理异常 file_id=%s", task.file_id)
        result = ocr.ExtractResult(error=f"{type(exc).__name__}: {exc}")

    if result.method == "skipped":
        _finish(db, task, status=OCRStatus.SKIPPED, error=result.error or "已跳过")
        write_audit(
            action=AuditAction.OCR_PROCESS, target_type="file", target_id=task.file_id,
            detail={"task_id": task.id, "status": "skipped", "reason": result.error},
        )
        return True

    if not result.ok and not result.has_text:
        task.retry_count = (task.retry_count or 0) + 1
        if task.retry_count < settings.OCR_MAX_RETRY:
            task.status = OCRStatus.QUEUED
            task.started_at = None
            task.error_msg = result.error
            db.commit()
            logger.warning("OCR 第 %d 次失败，稍后重试 file_id=%s: %s",
                           task.retry_count, task.file_id, result.error)
            return True
        _finish(db, task, status=OCRStatus.FAILED, error=result.error)
        write_audit(
            action=AuditAction.OCR_PROCESS, target_type="file", target_id=task.file_id,
            detail={"task_id": task.id, "status": "failed", "error": result.error},
            result="failure",
        )
        return True

    _finish(
        db, task, status=OCRStatus.READY,
        text=result.text, pages=result.pages, error=None,
    )
    write_audit(
        action=AuditAction.OCR_PROCESS, target_type="file", target_id=task.file_id,
        detail={
            "task_id": task.id, "status": "ready", "method": result.method,
            "engine": result.engine, "chars": len(result.text), "pages": result.pages,
        },
    )
    logger.info("OCR 完成 file_id=%s method=%s chars=%d",
                task.file_id, result.method, len(result.text))
    return True


def drain(db: Session, limit: int = 100) -> int:
    """把当前队列一次性跑空，主要用于命令行补跑与测试。"""
    processed = 0
    while processed < limit and process_once(db):
        processed += 1
    return processed


# ---------------------------------------------------------------- 线程管理
def start_worker() -> threading.Thread:
    """启动后台轮询线程（幂等）。"""
    global _thread
    if _thread is not None and _thread.is_alive():
        return _thread
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="ocr-worker", daemon=True)
    _thread.start()
    logger.info("OCR worker 已启动，间隔 %ss", settings.OCR_WORKER_INTERVAL_SECONDS)
    return _thread


def stop_worker(timeout: float = 5.0) -> None:
    global _thread
    _stop.set()
    if _thread is not None and _thread.is_alive():
        _thread.join(timeout=timeout)
    _thread = None
    logger.info("OCR worker 已停止")


def worker_alive() -> bool:
    return _thread is not None and _thread.is_alive()


def _loop() -> None:
    interval = max(1, settings.OCR_WORKER_INTERVAL_SECONDS)
    with SessionLocal() as db:
        backfill_queue(db)
        reset_stuck_tasks(db)
    idle_rounds = 0
    while not _stop.is_set():
        try:
            with SessionLocal() as db:
                worked = process_once(db)
            if worked:
                idle_rounds = 0
                continue
            idle_rounds += 1
            if idle_rounds % 60 == 0:  # 每约 5 分钟做一次自愈巡检
                with SessionLocal() as db:
                    reset_stuck_tasks(db)
            _stop.wait(interval)
        except Exception:  # noqa: BLE001  线程不能因单次异常退出
            logger.exception("OCR worker 循环异常")
            time.sleep(interval)
