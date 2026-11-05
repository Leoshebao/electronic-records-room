"""借阅审批与到期回收。

流程：申请 → 审批（通过/驳回）→ 借阅中（授予临时权限）→ 归还 / 到期自动失效。
设计约束：
1. 借阅授权落在 document_permissions 表（subject_type=user），带 expires_at；
2. 权限只能额外放行，不改变密级矩阵本身的判定顺序；
3. 到期回收由 sweeper 定时扫描，同时兜底删除过期授权，避免权限泄漏。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.permissions import can_access_level
from app.models.document import Document, DocumentPermission
from app.models.enums import AuditAction, BorrowStatus, Role
from app.models.user import User
from app.models.workflow import BorrowRequest

logger = logging.getLogger("erecords.borrow")

MIN_DAYS = 1
MAX_DAYS = 90
DEFAULT_DAYS = 7
MAX_RENEW = 2
ACTIVE_STATUSES = (BorrowStatus.PENDING.value, BorrowStatus.APPROVED.value)


# ---------------------------------------------------------------- 工具
def now() -> datetime:
    return datetime.now(timezone.utc)


def gen_request_no(db: Session) -> str:
    """BR + YYYYMMDD + 4 位当日序号。"""
    day = datetime.now().strftime("%Y%m%d")
    prefix = f"BR{day}"
    total = db.scalar(
        select(func.count()).select_from(BorrowRequest).where(
            BorrowRequest.request_no.like(f"{prefix}%")
        )
    ) or 0
    for i in range(1, 10000):
        candidate = f"{prefix}{(total + i):04d}"
        exists = db.scalar(
            select(func.count()).select_from(BorrowRequest).where(
                BorrowRequest.request_no == candidate
            )
        )
        if not exists:
            return candidate
    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="当日借阅单号已用尽")


def clamp_days(days: int | None) -> int:
    value = DEFAULT_DAYS if days is None else int(days)
    return max(MIN_DAYS, min(MAX_DAYS, value))


def _get_request(db: Session, request_id: int) -> BorrowRequest:
    req = db.get(BorrowRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="借阅申请不存在")
    return req


def _is_privileged(user: User) -> bool:
    return str(user.role) in (Role.SYSADMIN.value, Role.RECORDS_MANAGER.value)


def _ensure_owner_or_privileged(user: User, req: BorrowRequest) -> None:
    if req.applicant_id != user.id and not _is_privileged(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权操作他人的借阅申请")


def remaining_days(req: BorrowRequest) -> int:
    """剩余天数，向上取整；未批准或已结束时为 0。"""
    if req.status != BorrowStatus.APPROVED.value or req.due_at is None:
        return 0
    delta = req.due_at - now()
    if delta.total_seconds() <= 0:
        return 0
    return max(1, int((delta.total_seconds() + 86399) // 86400))


# ---------------------------------------------------------------- 授权
def _grant(db: Session, req: BorrowRequest, approver_id: int, can_download: bool, can_print: bool) -> None:
    """写入（或更新）该用户对该资料的临时查看授权。"""
    perm = db.scalar(
        select(DocumentPermission).where(
            DocumentPermission.document_id == req.document_id,
            DocumentPermission.subject_type == "user",
            DocumentPermission.subject_id == req.applicant_id,
        )
    )
    if perm is None:
        perm = DocumentPermission(
            document_id=req.document_id,
            subject_type="user",
            subject_id=req.applicant_id,
            can_view=True,
            can_download=can_download,
            can_print=can_print,
            granted_by=approver_id,
            expires_at=req.due_at,
        )
        db.add(perm)
    else:
        perm.can_view = True
        perm.can_download = perm.can_download or can_download
        perm.can_print = perm.can_print or can_print
        perm.granted_by = approver_id
        perm.expires_at = req.due_at if perm.expires_at is None else max(perm.expires_at, req.due_at)
    db.flush()


def _revoke(db: Session, req: BorrowRequest) -> None:
    """回收借阅产生的临时授权（不影响人工长期授权的其他位）。"""
    perm = db.scalar(
        select(DocumentPermission).where(
            DocumentPermission.document_id == req.document_id,
            DocumentPermission.subject_type == "user",
            DocumentPermission.subject_id == req.applicant_id,
        )
    )
    if perm is None:
        return
    # 到期即删除，避免过期行堆积；人工授权由后台另行维护
    db.delete(perm)
    db.flush()


def purge_expired_permissions(db: Session) -> int:
    rows = db.scalars(
        select(DocumentPermission).where(
            DocumentPermission.expires_at.is_not(None),
            DocumentPermission.expires_at <= now(),
        )
    ).all()
    for row in rows:
        db.delete(row)
    if rows:
        db.flush()
    return len(rows)


# ---------------------------------------------------------------- 主流程
def apply_for_borrow(
    db: Session,
    user: User,
    *,
    document_id: int,
    reason: str,
    days: int | None = None,
    can_download: bool = False,
    can_print: bool = False,
) -> BorrowRequest:
    doc = db.get(Document, document_id)
    if doc is None or doc.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
    if not reason or not reason.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="请填写借阅事由")

    # 已有在途申请时不重复提交
    dup = db.scalar(
        select(BorrowRequest).where(
            BorrowRequest.document_id == document_id,
            BorrowRequest.applicant_id == user.id,
            BorrowRequest.status.in_(list(ACTIVE_STATUSES)),
        )
    )
    if dup is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"该资料已有在途借阅申请（{dup.request_no}，状态 {dup.status}）",
        )

    req = BorrowRequest(
        request_no=gen_request_no(db),
        document_id=document_id,
        applicant_id=user.id,
        reason=reason.strip()[:2000],
        requested_days=clamp_days(days),
        want_download=can_download,
        want_print=can_print,
        status=BorrowStatus.PENDING.value,
    )
    db.add(req)
    db.flush()

    logger.info("借阅申请 %s 由用户 %s 提交，资料 %s", req.request_no, user.username, doc.doc_no)
    return req


def approve(
    db: Session,
    approver: User,
    request_id: int,
    *,
    days: int | None = None,
    can_download: bool | None = None,
    can_print: bool | None = None,
) -> BorrowRequest:
    req = _get_request(db, request_id)
    if req.status != BorrowStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"仅待审批的申请可通过，当前状态 {req.status}",
        )
    if req.applicant_id == approver.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="不可审批自己的借阅申请")

    span = clamp_days(days if days is not None else req.requested_days)
    req.status = BorrowStatus.APPROVED.value
    req.approver_id = approver.id
    req.approved_at = now()
    req.start_at = now()
    req.due_at = now() + timedelta(days=span)

    _grant(
        db,
        req,
        approver.id,
        req.want_download if can_download is None else can_download,
        req.want_print if can_print is None else can_print,
    )
    logger.info("借阅 %s 已批准，due=%s", req.request_no, req.due_at)
    return req


def reject(db: Session, approver: User, request_id: int, *, reason: str) -> BorrowRequest:
    req = _get_request(db, request_id)
    if req.status != BorrowStatus.PENDING.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"当前状态 {req.status} 不可驳回")
    if not reason or not reason.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="请填写驳回理由")
    req.status = BorrowStatus.REJECTED.value
    req.approver_id = approver.id
    req.approved_at = now()
    req.reject_reason = reason.strip()[:1000]
    return req


def cancel(db: Session, user: User, request_id: int) -> BorrowRequest:
    req = _get_request(db, request_id)
    if req.applicant_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能撤回自己的申请")
    if req.status not in (BorrowStatus.PENDING.value, BorrowStatus.APPROVED.value):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"当前状态 {req.status} 不可撤回")
    req.status = BorrowStatus.CANCELLED.value
    _revoke(db, req)
    return req


def return_doc(db: Session, user: User, request_id: int) -> BorrowRequest:
    req = _get_request(db, request_id)
    _ensure_owner_or_privileged(user, req)
    if req.status != BorrowStatus.APPROVED.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"当前状态 {req.status} 无需归还")
    req.status = BorrowStatus.RETURNED.value
    req.returned_at = now()
    _revoke(db, req)
    return req


def renew(db: Session, user: User, request_id: int, *, days: int | None = None) -> BorrowRequest:
    req = _get_request(db, request_id)
    _ensure_owner_or_privileged(user, req)
    if req.status != BorrowStatus.APPROVED.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"当前状态 {req.status} 不可续借")
    if req.renew_count >= MAX_RENEW:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"最多续借 {MAX_RENEW} 次")
    if req.due_at is not None and req.due_at <= now():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="借阅已到期，请重新申请")

    span = clamp_days(days if days is not None else DEFAULT_DAYS)
    req.renew_count += 1
    req.due_at = (req.due_at or now()) + timedelta(days=span)
    _grant(db, req, req.approver_id or user.id, False, False)
    return req


def expire_due(db: Session) -> list[BorrowRequest]:
    """把已到期的借阅置为 expired 并回收授权。返回本次处理的记录。"""
    rows = db.scalars(
        select(BorrowRequest).where(
            BorrowRequest.status == BorrowStatus.APPROVED.value,
            BorrowRequest.due_at.is_not(None),
            BorrowRequest.due_at <= now(),
        )
    ).all()
    for req in rows:
        req.status = BorrowStatus.EXPIRED.value
        req.returned_at = now()
        _revoke(db, req)
    if rows:
        db.flush()
    return list(rows)


def sweep(db: Session) -> dict:
    """到期回收 + 过期授权清理，供定时任务与手动接口复用。"""
    expired = expire_due(db)
    purged = purge_expired_permissions(db)
    return {
        "expired": len(expired),
        "purged_permissions": purged,
        "request_nos": [r.request_no for r in expired][:50],
    }


# ---------------------------------------------------------------- 查询
def can_view_document(db: Session, user: User, doc: Document) -> bool:
    if can_access_level(user.role, doc.secrecy_level):
        return True
    perm = db.scalar(
        select(DocumentPermission).where(
            DocumentPermission.document_id == doc.id,
            DocumentPermission.subject_type == "user",
            DocumentPermission.subject_id == user.id,
            DocumentPermission.can_view.is_(True),
            or_(
                DocumentPermission.expires_at.is_(None),
                DocumentPermission.expires_at > now(),
            ),
        )
    )
    return perm is not None


def active_borrow_ids(db: Session, user: User) -> list[int]:
    """该用户当前借阅中的资料 ID（未到期）。"""
    rows = db.scalars(
        select(BorrowRequest.document_id).where(
            BorrowRequest.applicant_id == user.id,
            BorrowRequest.status == BorrowStatus.APPROVED.value,
            BorrowRequest.due_at > now(),
        )
    ).all()
    return list(rows)


def list_requests(
    db: Session,
    user: User,
    *,
    status_list: Iterable[str] | None = None,
    mine: bool = True,
    keyword: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[tuple[BorrowRequest, Document, str | None]], int]:
    stmt = select(BorrowRequest, Document, User.username).join(
        Document, Document.id == BorrowRequest.document_id
    ).outerjoin(User, User.id == BorrowRequest.applicant_id)

    if mine or not _is_privileged(user):
        stmt = stmt.where(BorrowRequest.applicant_id == user.id)
    if status_list:
        values = [str(s) for s in status_list]
        stmt = stmt.where(BorrowRequest.status.in_(values))
    if keyword:
        like = f"%{keyword.strip()}%"
        stmt = stmt.where(
            or_(
                BorrowRequest.request_no.ilike(like),
                BorrowRequest.reason.ilike(like),
                Document.title.ilike(like),
                Document.doc_no.ilike(like),
            )
        )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(BorrowRequest.created_at.desc(), BorrowRequest.id.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [(r, d, name) for r, d, name in rows], total


def pending_count(db: Session) -> int:
    return db.scalar(
        select(func.count()).select_from(BorrowRequest).where(
            BorrowRequest.status == BorrowStatus.PENDING.value
        )
    ) or 0
