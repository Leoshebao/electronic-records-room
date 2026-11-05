"""审计日志查询与统计概览路由。

权限边界：
- /api/audit/*        需要 audit:view（系统管理员、档案管理员）
- /api/stats/overview 需要 doc:view，任何登录用户可看概览，但敏感明细做脱敏
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.models.enums import Permission
from app.db.session import get_db
from app.models.document import Document, DocumentVersion, FileObject
from app.models.enums import AuditAction, BorrowStatus, DocStatus, OCRStatus
from app.models.user import User
from app.models.workflow import AuditLog, BorrowRequest
from app.schemas.audit import (
    AuditActionItem,
    AuditOut,
    AuditPage,
    AuditSummary,
    StatsOverview,
)

audit_router = APIRouter(prefix="/audit", tags=["审计"])
router = APIRouter(prefix="/stats", tags=["统计"])

ACTION_LABELS: dict[str, str] = {
    "login": "登录",
    "login_failed": "登录失败",
    "logout": "退出登录",
    "doc_create": "新建资料",
    "doc_update": "修改资料",
    "doc_delete": "删除资料",
    "doc_view": "查看资料",
    "doc_download": "下载资料",
    "doc_print": "打印资料",
    "doc_search": "检索",
    "ocr_process": "OCR 解析",
    "borrow_apply": "借阅申请",
    "borrow_approve": "借阅批准",
    "borrow_reject": "借阅驳回",
    "borrow_return": "借阅归还",
    "borrow_renew": "借阅续借",
    "borrow_expire": "借阅到期",
    "user_create": "新建用户",
    "user_update": "修改用户",
    "user_disable": "停用用户",
    "perm_change": "权限变更",
    "config_change": "配置变更",
    "backup": "备份",
    "restore": "恢复",
}


@audit_router.get("/logs", response_model=AuditPage, summary="审计日志分页查询")
def list_audit_logs(
    action: str | None = None,
    username: str | None = None,
    result: str | None = None,
    target_type: str | None = None,
    keyword: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission(Permission.AUDIT_VIEW)),
) -> AuditPage:
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if username:
        stmt = stmt.where(AuditLog.username.ilike(f"%{username}%"))
    if result:
        stmt = stmt.where(AuditLog.result == result)
    if target_type:
        stmt = stmt.where(AuditLog.target_type == target_type)
    if keyword:
        stmt = stmt.where(cast(AuditLog.detail, String).ilike(f"%{keyword}%"))
    if start:
        stmt = stmt.where(AuditLog.created_at >= start)
    if end:
        stmt = stmt.where(AuditLog.created_at <= end)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * size).limit(size)
    ).all()
    return AuditPage(items=[AuditOut.model_validate(r) for r in rows], total=total, page=page, size=size)


@audit_router.get("/actions", response_model=list[AuditActionItem], summary="动作字典及各动作条数")
def audit_actions(
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission(Permission.AUDIT_VIEW)),
) -> list[AuditActionItem]:
    rows = db.execute(select(AuditLog.action, func.count()).group_by(AuditLog.action)).all()
    counts = {a: c for a, c in rows}
    items = [
        AuditActionItem(action=a.value, label=ACTION_LABELS.get(a.value, a.value), count=counts.get(a.value, 0))
        for a in AuditAction
    ]
    return sorted(items, key=lambda x: x.count, reverse=True)


@audit_router.get("/summary", response_model=AuditSummary, summary="审计概览")
def audit_summary(
    days: int = Query(7, ge=1, le=90),
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission(Permission.AUDIT_VIEW)),
) -> AuditSummary:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    total = db.scalar(select(func.count()).select_from(AuditLog)) or 0
    today = db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.created_at >= today_start)) or 0
    failed = db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.result != "success")) or 0

    by_action_rows = db.execute(
        select(AuditLog.action, func.count()).where(AuditLog.created_at >= since)
        .group_by(AuditLog.action).order_by(func.count().desc()).limit(12)
    ).all()
    by_user_rows = db.execute(
        select(AuditLog.username, func.count()).where(AuditLog.created_at >= since, AuditLog.username.isnot(None))
        .group_by(AuditLog.username).order_by(func.count().desc()).limit(10)
    ).all()

    return AuditSummary(
        total=total,
        today=today,
        failed=failed,
        by_action=[
            AuditActionItem(action=a, label=ACTION_LABELS.get(a, a), count=c) for a, c in by_action_rows
        ],
        by_user=[{"username": u, "count": c} for u, c in by_user_rows],
    )


@router.get("/overview", response_model=StatsOverview, summary="系统统计概览")
def stats_overview(
    days: int = Query(14, ge=7, le=90),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.DOC_VIEW)),
) -> StatsOverview:
    from app.core.config import settings
    from app.services.storage import stat_usage

    active = Document.status == DocStatus.ACTIVE
    total_docs = db.scalar(select(func.count()).select_from(Document).where(active)) or 0
    total_versions = db.scalar(
        select(func.count()).select_from(DocumentVersion)
        .join(Document, Document.id == DocumentVersion.document_id).where(active)
    ) or 0
    total_pages = db.scalar(select(func.coalesce(func.sum(Document.page_count), 0)).where(active)) or 0
    total_views = db.scalar(select(func.coalesce(func.sum(Document.view_count), 0)).where(active)) or 0
    total_downloads = db.scalar(select(func.coalesce(func.sum(Document.download_count), 0)).where(active)) or 0

    by_level = db.execute(
        select(Document.secrecy_level, func.count()).where(active).group_by(Document.secrecy_level)
    ).all()
    by_room = db.execute(
        select(Document.room_id, func.count()).where(active).group_by(Document.room_id)
    ).all()
    by_year = db.execute(
        select(Document.archive_year, func.count()).where(active, Document.archive_year.isnot(None))
        .group_by(Document.archive_year).order_by(Document.archive_year.desc()).limit(10)
    ).all()

    usage = stat_usage()
    disk_total = disk_free = None
    try:
        import shutil as _shutil

        du = _shutil.disk_usage(str(settings.storage_path))
        disk_total = round(du.total / 1024 / 1024 / 1024, 1)
        disk_free = round(du.free / 1024 / 1024 / 1024, 1)
    except Exception:  # noqa: BLE001 - 磁盘信息拿不到不影响概览
        pass
    storage_info = {
        "total_bytes": usage.get("total_bytes", 0),
        "total_mb": usage.get("total_mb", 0),
        "total_files": usage.get("file_count", 0),
        "storage_root": str(settings.storage_path),
        "disk_total_gb": disk_total,
        "disk_free_gb": disk_free,
    }

    now = datetime.now(timezone.utc)
    borrow_rows = db.execute(
        select(BorrowRequest.status, func.count()).group_by(BorrowRequest.status)
    ).all()
    borrow_map = {str(s): c for s, c in borrow_rows}
    overdue = db.scalar(
        select(func.count()).select_from(BorrowRequest).where(
            BorrowRequest.status == BorrowStatus.APPROVED,
            BorrowRequest.due_at.isnot(None),
            BorrowRequest.due_at < now,
        )
    ) or 0
    borrow = {
        "total": sum(borrow_map.values()),
        "pending": borrow_map.get(BorrowStatus.PENDING.value, 0),
        "approved": borrow_map.get(BorrowStatus.APPROVED.value, 0),
        "overdue": overdue,
        "returned": borrow_map.get(BorrowStatus.RETURNED.value, 0),
        "rejected": borrow_map.get(BorrowStatus.REJECTED.value, 0),
    }

    ocr_rows = db.execute(select(FileObject.ocr_status, func.count()).group_by(FileObject.ocr_status)).all()
    ocr_map = {str(s): c for s, c in ocr_rows}
    ocr = {
        "total": sum(ocr_map.values()),
        "ready": ocr_map.get(OCRStatus.READY.value, 0),
        "queued": ocr_map.get(OCRStatus.QUEUED.value, 0),
        "processing": ocr_map.get(OCRStatus.PROCESSING.value, 0),
        "failed": ocr_map.get(OCRStatus.FAILED.value, 0),
    }

    user_rows = db.execute(select(User.role, func.count()).where(User.is_active.is_(True)).group_by(User.role)).all()
    users = {
        "active_total": sum(c for _r, c in user_rows),
        "by_role": {str(r): c for r, c in user_rows},
    }

    # 近 N 天新增资料 / 下载趋势
    since = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    created_rows = db.execute(
        select(func.date(Document.created_at), func.count())
        .where(Document.created_at >= since).group_by(func.date(Document.created_at))
    ).all()
    dl_rows = db.execute(
        select(func.date(AuditLog.created_at), func.count())
        .where(AuditLog.created_at >= since, AuditLog.action == AuditAction.DOC_DOWNLOAD.value)
        .group_by(func.date(AuditLog.created_at))
    ).all()
    vw_rows = db.execute(
        select(func.date(AuditLog.created_at), func.count())
        .where(AuditLog.created_at >= since, AuditLog.action == AuditAction.DOC_VIEW.value)
        .group_by(func.date(AuditLog.created_at))
    ).all()
    c_map = {str(d): c for d, c in created_rows}
    d_map = {str(d): c for d, c in dl_rows}
    v_map = {str(d): c for d, c in vw_rows}
    trend = []
    for i in range(days):
        day = (since + timedelta(days=i)).date().isoformat()
        trend.append({
            "date": day,
            "created": c_map.get(day, 0),
            "downloads": d_map.get(day, 0),
            "views": v_map.get(day, 0),
        })

    top_rows = db.scalars(
        select(Document).where(active)
        .order_by((Document.view_count + Document.download_count).desc()).limit(8)
    ).all()
    top_documents = [
        {
            "id": d.id, "title": d.title, "doc_no": d.doc_no,
            "secrecy_level": str(d.secrecy_level), "views": d.view_count, "downloads": d.download_count,
        }
        for d in top_rows
    ]

    return StatsOverview(
        documents={
            "total": total_docs,
            "versions": total_versions,
            "pages": int(total_pages),
            "views": int(total_views),
            "downloads": int(total_downloads),
            "by_level": {str(k): v for k, v in by_level},
            "by_room": {str(k): v for k, v in by_room},
            "by_year": {str(k): v for k, v in by_year},
        },
        storage=storage_info,
        borrow=borrow,
        ocr=ocr,
        users=users,
        trend=trend,
        top_documents=top_documents,
    )
