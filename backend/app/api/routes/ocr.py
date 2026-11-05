"""OCR 任务管理接口：状态查询、重排、手动补跑、引擎自检。

普通查阅者无权访问；档案管理员可对资料重排解析，系统管理员额外可触发全库补跑。
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.config import settings
from app.db.session import get_db
from app.models.document import Document, FileObject
from app.models.enums import AuditAction, OCRStatus, Permission
from app.models.user import User
from app.models.workflow import OCRTask
from app.services import ocr, ocr_worker
from app.services.audit import write_audit

router = APIRouter(prefix="/ocr", tags=["OCR 解析"])


class TaskOut(BaseModel):
    id: int
    file_id: int
    status: str
    engine: str
    retry_count: int
    error_msg: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    created_at: datetime
    filename: str | None = None
    document_id: int | None = None
    doc_no: str | None = None

    model_config = {"from_attributes": True}


class RunResult(BaseModel):
    created: int = 0
    processed: int = 0
    message: str = "ok"


@router.get("/engine", summary="OCR 引擎自检")
def engine_status(_: User = Depends(require_permission(Permission.DOC_UPLOAD))) -> dict:
    info = ocr.ocr_engine_status()
    info.update(
        {
            "enabled": settings.OCR_ENABLED,
            "worker_enabled": settings.OCR_WORKER_ENABLED,
            "worker_alive": ocr_worker.worker_alive(),
            "max_retry": settings.OCR_MAX_RETRY,
            "max_pages": settings.OCR_MAX_PAGES,
        }
    )
    return info


@router.get("/stats", summary="任务状态统计")
def stats(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.DOC_UPLOAD)),
) -> dict:
    task_rows = db.execute(
        select(OCRTask.status, func.count(OCRTask.id)).group_by(OCRTask.status)
    ).all()
    file_rows = db.execute(
        select(FileObject.ocr_status, func.count(FileObject.id))
        .where(FileObject.status == "stored")
        .group_by(FileObject.ocr_status)
    ).all()
    return {
        "tasks": {str(k): v for k, v in task_rows},
        "files": {str(k): v for k, v in file_rows},
        "pending": sum(v for k, v in task_rows if k in (OCRStatus.QUEUED, OCRStatus.PROCESSING)),
        "worker_alive": ocr_worker.worker_alive(),
    }


@router.get("/tasks", summary="任务列表")
def list_tasks(
    status_filter: str | None = Query(None, alias="status", description="按状态过滤"),
    document_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.DOC_UPLOAD)),
) -> dict:
    stmt = select(OCRTask, FileObject).join(FileObject, FileObject.id == OCRTask.file_id)
    count_stmt = select(func.count(OCRTask.id)).join(
        FileObject, FileObject.id == OCRTask.file_id
    )
    if status_filter:
        try:
            st = OCRStatus(status_filter)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"非法状态：{status_filter}") from None
        stmt = stmt.where(OCRTask.status == st)
        count_stmt = count_stmt.where(OCRTask.status == st)
    if document_id:
        stmt = stmt.where(FileObject.document_id == document_id)
        count_stmt = count_stmt.where(FileObject.document_id == document_id)

    total = db.scalar(count_stmt) or 0
    rows = db.execute(
        stmt.order_by(OCRTask.id.desc()).offset((page - 1) * size).limit(size)
    ).all()

    items = []
    for task, file_obj in rows:
        doc = db.get(Document, file_obj.document_id)
        items.append(
            TaskOut(
                id=task.id, file_id=task.file_id, status=str(task.status),
                engine=task.engine, retry_count=task.retry_count,
                error_msg=task.error_msg, started_at=task.started_at,
                finished_at=task.finished_at, duration_ms=task.duration_ms,
                created_at=task.created_at, filename=file_obj.original_name,
                document_id=file_obj.document_id, doc_no=doc.doc_no if doc else None,
            )
        )
    return {
        "items": items,
        "meta": {
            "total": total, "page": page, "size": size,
            "pages": (total + size - 1) // size if size else 0,
        },
    }


@router.post("/documents/{doc_id}/reocr", summary="整份资料重新解析")
def reocr_document(
    doc_id: int,
    request: Request,
    run_now: bool = Query(True, description="是否立即同步跑一次队列"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.DOC_EDIT)),
) -> RunResult:
    doc = db.get(Document, doc_id)
    if doc is None or doc.is_deleted:
        raise HTTPException(status_code=404, detail="资料不存在")

    for file_obj in db.scalars(
        select(FileObject).where(FileObject.document_id == doc.id, FileObject.status == "stored")
    ).all():
        file_obj.ocr_status = OCRStatus.QUEUED
        file_obj.ocr_text = None
    db.commit()

    created = ocr_worker.enqueue_document(db, doc, only_missing=False)
    db.commit()
    processed = ocr_worker.drain(db) if run_now else 0
    write_audit(
        action=AuditAction.OCR_PROCESS, user=user, target_type="document", target_id=doc.id,
        detail={"action": "reocr", "created": created, "processed": processed},
        request=request,
    )
    return RunResult(
        created=created, processed=processed,
        message=f"已重排 {created} 个文件，即时处理 {processed} 个" if run_now else f"已重排 {created} 个文件",
    )


@router.post("/files/{file_id}/retry", summary="单个文件重试")
def retry_file(
    file_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.DOC_EDIT)),
) -> RunResult:
    file_obj = db.get(FileObject, file_id)
    if file_obj is None or file_obj.status != "stored":
        raise HTTPException(status_code=404, detail="文件不存在")
    file_obj.ocr_status = OCRStatus.QUEUED
    task = ocr_worker.enqueue_file(db, file_obj)
    if task is not None:
        task.retry_count = 0
    db.commit()
    write_audit(
        action=AuditAction.OCR_PROCESS, user=user, target_type="file", target_id=file_obj.id,
        detail={"action": "retry"}, request=request,
    )
    return RunResult(created=1 if task else 0, message="已重新排队" if task else "已在队列中")


@router.post("/drain", summary="立即跑空队列")
def drain_queue(
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.DOC_UPLOAD)),
) -> RunResult:
    processed = ocr_worker.drain(db, limit=limit)
    return RunResult(processed=processed, message=f"已处理 {processed} 个任务")


@router.post("/worker/start", summary="启动后台解析线程")
def start_worker(_: User = Depends(require_permission(Permission.SYSTEM_CONFIG))) -> dict:
    ocr_worker.start_worker()
    return {"ok": True, "worker_alive": ocr_worker.worker_alive()}


@router.post("/worker/stop", summary="停止后台解析线程")
def stop_worker(_: User = Depends(require_permission(Permission.SYSTEM_CONFIG))) -> dict:
    ocr_worker.stop_worker()
    return {"ok": True, "worker_alive": ocr_worker.worker_alive()}
