"""借阅审批接口：申请、审批、驳回、撤回、归还、续借、到期回收。

权限约定：
- 申请 / 撤回 / 归还 / 续借：borrow:apply（三角色均有），且只能操作自己的单子；
- 审批 / 驳回 / 待办列表 / 手动回收：borrow:approve（管理员与档案管理员）。
"""
from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.config import settings
from app.db.session import get_db
from app.models.document import Document
from app.models.enums import AuditAction, BorrowStatus, Permission, SecrecyLevel, Role
from app.models.user import User
from app.models.workflow import BorrowRequest
from app.schemas.borrow import (
    BorrowApplyIn,
    BorrowApproveIn,
    BorrowBrief,
    BorrowPage,
    BorrowRejectIn,
    BorrowRenewIn,
    SweeperStatus,
    SweepResult,
)
from app.services import borrow as borrow_service
from app.services import borrow_sweeper
from app.services.audit import write_audit

router = APIRouter(prefix="/borrow", tags=["借阅审批"])

_MANAGER_ROLES = (Role.SYSADMIN.value, Role.RECORDS_MANAGER.value)


def _brief(req: BorrowRequest, doc: Document | None, applicant_name: str | None) -> BorrowBrief:
    return BorrowBrief(
        id=req.id,
        request_no=req.request_no,
        document_id=req.document_id,
        doc_no=doc.doc_no if doc else None,
        title=doc.title if doc else None,
        secrecy_level=str(doc.secrecy_level) if doc else None,
        applicant_id=req.applicant_id,
        applicant_name=applicant_name,
        reason=req.reason,
        status=req.status,
        requested_days=req.requested_days,
        want_download=req.want_download,
        want_print=req.want_print,
        approver_id=req.approver_id,
        approved_at=req.approved_at,
        reject_reason=req.reject_reason,
        start_at=req.start_at,
        due_at=req.due_at,
        returned_at=req.returned_at,
        renew_count=req.renew_count,
        remaining_days=borrow_service.remaining_days(req),
        created_at=req.created_at,
    )


@router.post("/requests", response_model=BorrowBrief, status_code=status.HTTP_201_CREATED,
             summary="提交借阅申请")
def apply_borrow(
    payload: BorrowApplyIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.BORROW_APPLY)),
) -> BorrowBrief:
    req = borrow_service.apply_for_borrow(
        db,
        user,
        document_id=payload.document_id,
        reason=payload.reason,
        days=payload.days,
        can_download=payload.can_download,
        can_print=payload.can_print,
    )
    doc = db.get(Document, req.document_id)
    db.commit()
    write_audit(
        action=AuditAction.BORROW_APPLY,
        user=user,
        target_type="borrow_request",
        target_id=req.id,
        detail={"request_no": req.request_no, "document_id": req.document_id,
                "days": req.requested_days},
        request=request,
    )
    db.refresh(req)
    return _brief(req, doc, user.username)


@router.get("/requests", response_model=BorrowPage, summary="借阅申请列表")
def list_borrow_requests(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.BORROW_APPLY)),
    mine: bool = Query(True, description="true 只看自己的；管理员可传 false 看全部"),
    status_filter: list[str] | None = Query(None, alias="status", description="可多值：pending/approved/..."),
    keyword: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> BorrowPage:
    rows, total = borrow_service.list_requests(
        db, user, status_list=status_filter, mine=mine, keyword=keyword,
        offset=(page - 1) * size, limit=size,
    )
    items = [_brief(r, d, name) for r, d, name in rows]
    return BorrowPage(
        items=items,
        total=total,
        page=page,
        size=size,
        pages=max(1, math.ceil(total / size)),
        pending_total=borrow_service.pending_count(db),
    )


@router.get("/pending", response_model=BorrowPage, summary="待审批列表（管理员）")
def pending_requests(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.BORROW_APPROVE)),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> BorrowPage:
    rows, total = borrow_service.list_requests(
        db, _, status_list=[BorrowStatus.PENDING.value], mine=False,
        offset=(page - 1) * size, limit=size,
    )
    return BorrowPage(
        items=[_brief(r, d, name) for r, d, name in rows],
        total=total,
        page=page,
        size=size,
        pages=max(1, math.ceil(total / size)),
        pending_total=total,
    )


@router.get("/mine", response_model=BorrowPage, summary="我的借阅（借阅中优先）")
def my_borrows(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.BORROW_APPLY)),
    active_only: bool = Query(False, description="只看借阅中的"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
) -> BorrowPage:
    statuses = [BorrowStatus.APPROVED.value] if active_only else None
    rows, total = borrow_service.list_requests(
        db, user, status_list=statuses, mine=True,
        offset=(page - 1) * size, limit=size,
    )
    return BorrowPage(
        items=[_brief(r, d, name) for r, d, name in rows],
        total=total,
        page=page,
        size=size,
        pages=max(1, math.ceil(total / size)),
        pending_total=borrow_service.pending_count(db),
    )


@router.get("/requests/{request_id}", response_model=BorrowBrief, summary="借阅详情")
def get_borrow_request(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.BORROW_APPLY)),
) -> BorrowBrief:
    req = db.get(BorrowRequest, request_id)
    if req is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="借阅申请不存在")
    if req.applicant_id != user.id and str(user.role) not in _MANAGER_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权查看他人的借阅申请")
    doc = db.get(Document, req.document_id)
    applicant = db.get(User, req.applicant_id)
    return _brief(req, doc, applicant.username if applicant else None)


@router.post("/requests/{request_id}/approve", response_model=BorrowBrief, summary="审批通过")
def approve_borrow(
    request_id: int,
    payload: BorrowApproveIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.BORROW_APPROVE)),
) -> BorrowBrief:
    req = borrow_service.approve(
        db, user, request_id,
        days=payload.days, can_download=payload.can_download, can_print=payload.can_print,
    )
    doc = db.get(Document, req.document_id)
    applicant = db.get(User, req.applicant_id)
    db.commit()
    write_audit(
        action=AuditAction.BORROW_APPROVE,
        user=user,
        target_type="borrow_request",
        target_id=req.id,
        detail={"request_no": req.request_no, "document_id": req.document_id,
                "due_at": req.due_at.isoformat() if req.due_at else None},
        request=request,
    )
    db.refresh(req)
    return _brief(req, doc, applicant.username if applicant else None)


@router.post("/requests/{request_id}/reject", response_model=BorrowBrief, summary="审批驳回")
def reject_borrow(
    request_id: int,
    payload: BorrowRejectIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.BORROW_APPROVE)),
) -> BorrowBrief:
    req = borrow_service.reject(db, user, request_id, reason=payload.reason)
    doc = db.get(Document, req.document_id)
    applicant = db.get(User, req.applicant_id)
    db.commit()
    write_audit(
        action=AuditAction.BORROW_REJECT,
        user=user,
        target_type="borrow_request",
        target_id=req.id,
        detail={"request_no": req.request_no, "reason": payload.reason},
        request=request,
    )
    db.refresh(req)
    return _brief(req, doc, applicant.username if applicant else None)


@router.post("/requests/{request_id}/cancel", response_model=BorrowBrief, summary="撤回申请")
def cancel_borrow(
    request_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.BORROW_APPLY)),
) -> BorrowBrief:
    req = borrow_service.cancel(db, user, request_id)
    doc = db.get(Document, req.document_id)
    db.commit()
    write_audit(
        action=AuditAction.BORROW_RETURN,
        user=user,
        target_type="borrow_request",
        target_id=req.id,
        detail={"request_no": req.request_no, "action": "cancel"},
        request=request,
    )
    db.refresh(req)
    return _brief(req, doc, user.username)


@router.post("/requests/{request_id}/return", response_model=BorrowBrief, summary="归还")
def return_borrow(
    request_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.BORROW_APPLY)),
) -> BorrowBrief:
    req = borrow_service.return_doc(db, user, request_id)
    doc = db.get(Document, req.document_id)
    applicant = db.get(User, req.applicant_id)
    db.commit()
    write_audit(
        action=AuditAction.BORROW_RETURN,
        user=user,
        target_type="borrow_request",
        target_id=req.id,
        detail={"request_no": req.request_no, "action": "return"},
        request=request,
    )
    db.refresh(req)
    return _brief(req, doc, applicant.username if applicant else None)


@router.post("/requests/{request_id}/renew", response_model=BorrowBrief, summary="续借")
def renew_borrow(
    request_id: int,
    payload: BorrowRenewIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.BORROW_APPLY)),
) -> BorrowBrief:
    req = borrow_service.renew(db, user, request_id, days=payload.days)
    doc = db.get(Document, req.document_id)
    applicant = db.get(User, req.applicant_id)
    db.commit()
    write_audit(
        action=AuditAction.BORROW_RENEW,
        user=user,
        target_type="borrow_request",
        target_id=req.id,
        detail={"request_no": req.request_no, "renew_count": req.renew_count,
                "due_at": req.due_at.isoformat() if req.due_at else None},
        request=request,
    )
    db.refresh(req)
    return _brief(req, doc, applicant.username if applicant else None)


@router.post("/sweep", response_model=SweepResult, summary="手动触发到期回收（管理员）")
def sweep_now(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.BORROW_APPROVE)),
) -> SweepResult:
    result = borrow_service.sweep(db)
    db.commit()
    write_audit(
        action=AuditAction.BORROW_EXPIRE,
        user=user,
        target_type="borrow_request",
        detail={"by": "manual", **result},
        request=request,
    )
    return SweepResult(**result)


@router.get("/sweeper", response_model=SweeperStatus, summary="到期回收线程状态")
def sweeper_status(
    _: User = Depends(require_permission(Permission.BORROW_APPROVE)),
) -> SweeperStatus:
    info = borrow_sweeper.worker_status()
    return SweeperStatus(
        enabled=bool(getattr(settings, "BORROW_SWEEP_ENABLED", True)),
        alive=info["alive"],
        interval=info["interval"],
        last_run=info["last_run"],
        last_result=info["last_result"],
    )


@router.get("/levels", summary="当前用户可借阅的密级范围")
def borrow_levels(
    user: User = Depends(require_permission(Permission.BORROW_APPLY)),
) -> dict:
    from app.api.deps import level_filter_values

    return {
        "role": str(user.role),
        "levels": level_filter_values(user),
        "all_levels": [lv.value for lv in SecrecyLevel],
        "note": "超出密级范围的资料需提交借阅申请，审批通过后获得临时查看权",
    }
