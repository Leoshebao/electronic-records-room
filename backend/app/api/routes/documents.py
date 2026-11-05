"""资料管理接口：上传、检索、详情、改元数据、版本、删除。

密级规则在此处二次把关：即使是资料员，也不能上传高于自身可见上限的密级，
避免"上传后自己看不见"的管理死角。
"""
from __future__ import annotations

import logging
import math
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, level_filter_values, require_permission
from app.core.config import settings
from app.core.permissions import can_access_level
from app.db.session import get_db
from app.models.document import Document, DocumentVersion, FileObject
from app.models.enums import AuditAction, DocStatus, OCRStatus, Permission, SecrecyLevel
from app.models.room import Category
from app.models.user import User
from app.schemas.document import (
    DocumentBrief,
    DocumentDetail,
    DocumentPage,
    DocumentUpdate,
    FileBrief,
    PageMeta,
    StorageUsage,
    VersionBrief,
)
from app.services import ocr_worker, storage
from app.services.audit import write_audit
from app.services.documents import (
    ensure_doc_access,
    ensure_visible,
    generate_doc_no,
    get_document_or_404,
    get_room_or_404,
    recalc_doc_stats,
    refresh_search_text,
    sanity_level,
    visible_doc_query,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])


def _check_category(db: Session, room_id: int, category_id: int | None) -> None:
    if category_id is None:
        return
    cat = db.get(Category, category_id)
    if cat is None or cat.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="类目不存在")
    if cat.room_id != room_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="所选类目不属于该资料室"
        )


def _check_upload_level(user: User, level: SecrecyLevel) -> None:
    if not can_access_level(user.role, level):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"您无权管理「{level.value}」级资料，请降低密级或联系系统管理员",
        )


def _detail(db: Session, doc: Document) -> DocumentDetail:
    files = db.scalars(
        select(FileObject).where(
            FileObject.document_id == doc.id, FileObject.status == "stored"
        ).order_by(FileObject.id)
    ).all()
    versions = db.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == doc.id)
        .order_by(DocumentVersion.version_no.desc())
    ).all()
    data = DocumentDetail.model_validate(doc)
    data.files = [FileBrief.model_validate(f) for f in files]
    data.versions = [VersionBrief.model_validate(v) for v in versions]
    return data


@router.post("/upload", response_model=DocumentDetail, status_code=status.HTTP_201_CREATED)
def upload_document(
    request: Request,
    room_id: int = Form(..., description="资料室 ID"),
    title: str = Form(..., min_length=1, max_length=500),
    category_id: int | None = Form(None),
    doc_no: str | None = Form(None, description="留空则按 室编码-年度-流水 自动生成"),
    secrecy_level: str = Form(SecrecyLevel.INTERNAL.value),
    summary: str | None = Form(None),
    keywords: str | None = Form(None),
    archive_year: int | None = Form(None),
    retention_years: int | None = Form(None),
    responsible_dept_id: int | None = Form(None),
    change_note: str | None = Form(None),
    files: list[UploadFile] = File(..., description="一个或多个文件"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.DOC_UPLOAD)),
) -> DocumentDetail:
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请至少上传一个文件")
    if len(files) > settings.BATCH_UPLOAD_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"单次最多上传 {settings.BATCH_UPLOAD_LIMIT} 个文件",
        )

    room = get_room_or_404(db, room_id)
    _check_category(db, room_id, category_id)
    level = sanity_level(secrecy_level)
    _check_upload_level(user, level)

    final_no = (doc_no or "").strip() or generate_doc_no(db, room, archive_year)

    doc = Document(
        doc_no=final_no,
        title=title.strip(),
        room_id=room_id,
        category_id=category_id,
        secrecy_level=level,
        status=DocStatus.ACTIVE,
        summary=summary,
        keywords=keywords,
        responsible_dept_id=responsible_dept_id or user.department_id,
        created_by=user.id,
        archive_year=archive_year or datetime.now().year,
        retention_years=retention_years,
    )
    db.add(doc)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"档号「{final_no}」已存在"
        ) from None

    ver_no, label = 1, "V1.0"
    version = DocumentVersion(
        document_id=doc.id,
        version_no=ver_no,
        version_label=label,
        change_note=change_note or "首次入库",
        is_current=True,
        created_by=user.id,
    )
    db.add(version)
    db.flush()

    saved: list[dict] = []
    try:
        for up in files:
            info = storage.save_upload(up, created_by=user.id)
            saved.append(info)
            db.add(FileObject(
                document_id=doc.id,
                version_id=version.id,
                original_name=info["original_name"],
                stored_name=info["stored_name"],
                rel_path=info["rel_path"],
                ext=info["ext"],
                mime_type=info["mime_type"],
                size_bytes=info["size_bytes"],
                sha256=info["sha256"],
                status="stored",
                ocr_status=OCRStatus.QUEUED,
                created_by=user.id,
            ))
        doc.current_version_id = version.id
        db.flush()
        recalc_doc_stats(db, doc)
        # 入库即排入 OCR 队列：worker 在后台抽文本，不阻塞上传响应
        ocr_worker.enqueue_document(db, doc, only_missing=False)
        refresh_search_text(db, doc)
        db.commit()
    except HTTPException:
        db.rollback()
        for info in saved:
            storage.remove_physical(info["rel_path"])
        raise
    except Exception:
        db.rollback()
        for info in saved:
            storage.remove_physical(info["rel_path"])
        logger.exception("资料入库失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="资料入库失败，请重试"
        ) from None

    db.refresh(doc)
    write_audit(
        action=AuditAction.DOC_CREATE, user=user, target_type="document", target_id=doc.id,
        detail={"doc_no": doc.doc_no, "files": len(saved), "level": level.value},
        request=request,
    )
    return _detail(db, doc)


@router.get("", response_model=DocumentPage)
def list_documents(
    keyword: str | None = Query(None, description="档号/题名/摘要/关键词/OCR 全文"),
    room_id: int | None = None,
    category_id: int | None = None,
    secrecy_level: str | None = None,
    status_: str | None = Query(None, alias="status"),
    archive_year: int | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    sort: str = Query("created_at", pattern="^(created_at|updated_at|title|doc_no|archive_year)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.DOC_VIEW)),
) -> DocumentPage:
    stmt = visible_doc_query(user, db)

    if room_id:
        stmt = stmt.where(Document.room_id == room_id)
    if category_id:
        cat = db.get(Category, category_id)
        if cat is None or cat.is_deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="类目不存在")
        sub_ids = db.scalars(
            select(Category.id).where(
                Category.room_id == cat.room_id,
                Category.path.like(f"{cat.path}%"),
                Category.is_deleted.is_(False),
            )
        ).all()
        stmt = stmt.where(Document.category_id.in_(list(sub_ids) or [-1]))
    if secrecy_level:
        lv = sanity_level(secrecy_level)
        if lv.value not in level_filter_values(user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该密级超出您的访问范围")
        stmt = stmt.where(Document.secrecy_level == lv)
    if status_:
        stmt = stmt.where(Document.status == status_)
    if archive_year:
        stmt = stmt.where(Document.archive_year == archive_year)

    if keyword:
        kw = f"%{keyword.strip()}%"
        stmt = stmt.where(or_(
            Document.doc_no.ilike(kw),
            Document.title.ilike(kw),
            Document.summary.ilike(kw),
            Document.keywords.ilike(kw),
            Document.search_text.ilike(kw),
        ))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    col = getattr(Document, sort)
    stmt = stmt.order_by(col.desc() if order == "desc" else col.asc(), Document.id.desc())
    rows = db.scalars(stmt.offset((page - 1) * size).limit(size)).all()

    return DocumentPage(
        items=[DocumentBrief.model_validate(r) for r in rows],
        meta=PageMeta(total=total, page=page, size=size, pages=math.ceil(total / size) if total else 0),
    )


@router.get("/{doc_id}", response_model=DocumentDetail)
def read_document(
    doc_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.DOC_VIEW)),
) -> DocumentDetail:
    doc = get_document_or_404(db, doc_id)
    ensure_doc_access(db, user, doc)
    doc.view_count = (doc.view_count or 0) + 1
    db.commit()
    db.refresh(doc)
    write_audit(
        action=AuditAction.DOC_VIEW, user=user, target_type="document", target_id=doc.id,
        detail={"doc_no": doc.doc_no}, request=request,
    )
    return _detail(db, doc)


@router.patch("/{doc_id}", response_model=DocumentDetail)
def update_document(
    doc_id: int,
    payload: DocumentUpdate,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.DOC_EDIT)),
) -> DocumentDetail:
    doc = get_document_or_404(db, doc_id)
    ensure_visible(user, doc)

    data = payload.model_dump(exclude_unset=True)
    if "secrecy_level" in data and data["secrecy_level"] is not None:
        _check_upload_level(user, SecrecyLevel(data["secrecy_level"]))
    if "category_id" in data:
        _check_category(db, doc.room_id, data["category_id"])

    change_note = data.pop("change_note", None)
    changed = {k: v for k, v in data.items() if getattr(doc, k, None) != v}
    for k, v in changed.items():
        setattr(doc, k, v)

    if changed:
        doc.updated_by = user.id
        ver = db.get(DocumentVersion, doc.current_version_id) if doc.current_version_id else None
        if ver is not None and change_note:
            ver.change_note = (ver.change_note or "") + f"\n元数据更新：{change_note}"
        refresh_search_text(db, doc)
        db.commit()
        write_audit(
            action=AuditAction.DOC_UPDATE, user=user, target_type="document", target_id=doc.id,
            detail={"fields": list(changed.keys())}, request=request,
        )
    db.refresh(doc)
    return _detail(db, doc)


@router.post("/{doc_id}/versions", response_model=DocumentDetail, status_code=status.HTTP_201_CREATED)
def add_version(
    doc_id: int,
    request: Request,
    files: list[UploadFile] = File(...),
    change_note: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.DOC_EDIT)),
) -> DocumentDetail:
    doc = get_document_or_404(db, doc_id)
    ensure_visible(user, doc)
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请至少上传一个文件")

    from app.services.documents import next_version

    no, label = next_version(db, doc)
    db.query(DocumentVersion).filter(
        DocumentVersion.document_id == doc.id, DocumentVersion.is_current.is_(True)
    ).update({"is_current": False}, synchronize_session=False)

    version = DocumentVersion(
        document_id=doc.id, version_no=no, version_label=label,
        change_note=change_note or f"第 {no} 次修订", is_current=True, created_by=user.id,
    )
    db.add(version)
    db.flush()

    saved: list[dict] = []
    try:
        for up in files:
            info = storage.save_upload(up, created_by=user.id)
            saved.append(info)
            db.add(FileObject(
                document_id=doc.id, version_id=version.id,
                original_name=info["original_name"], stored_name=info["stored_name"],
                rel_path=info["rel_path"], ext=info["ext"], mime_type=info["mime_type"],
                size_bytes=info["size_bytes"], sha256=info["sha256"],
                status="stored", ocr_status=OCRStatus.QUEUED, created_by=user.id,
            ))
        doc.current_version_id = version.id
        doc.updated_by = user.id
        db.flush()
        recalc_doc_stats(db, doc)
        # 新版本文件同样排入 OCR 队列
        ocr_worker.enqueue_document(db, doc, only_missing=False)
        refresh_search_text(db, doc)
        db.commit()
    except Exception:
        db.rollback()
        for info in saved:
            storage.remove_physical(info["rel_path"])
        logger.exception("新增版本失败")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="新增版本失败，请重试"
        ) from None

    db.refresh(doc)
    write_audit(
        action=AuditAction.DOC_UPDATE, user=user, target_type="document", target_id=doc.id,
        detail={"version": label, "files": len(saved)}, request=request,
    )
    return _detail(db, doc)


@router.get("/{doc_id}/versions", response_model=list[VersionBrief])
def list_versions(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.DOC_VIEW)),
) -> list[VersionBrief]:
    doc = get_document_or_404(db, doc_id)
    ensure_doc_access(db, user, doc)
    rows = db.scalars(
        select(DocumentVersion)
        .where(DocumentVersion.document_id == doc_id)
        .order_by(DocumentVersion.version_no.desc())
    ).all()
    return [VersionBrief.model_validate(r) for r in rows]


@router.post("/{doc_id}/versions/{version_id}/rollback", response_model=DocumentDetail)
def rollback_version(
    doc_id: int,
    version_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.DOC_EDIT)),
) -> DocumentDetail:
    """回滚到历史版本：不删除任何数据，仅把指定版本重新置为当前版本。"""
    doc = get_document_or_404(db, doc_id)
    ensure_visible(user, doc)
    version = db.get(DocumentVersion, version_id)
    if version is None or version.document_id != doc.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="版本不存在")
    if doc.current_version_id == version.id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="该版本已是当前版本")

    prev_id = doc.current_version_id
    db.query(DocumentVersion).filter(
        DocumentVersion.document_id == doc.id, DocumentVersion.is_current.is_(True)
    ).update({"is_current": False}, synchronize_session=False)
    version.is_current = True
    doc.current_version_id = version.id
    doc.updated_by = user.id
    db.flush()
    recalc_doc_stats(db, doc)
    refresh_search_text(db, doc)
    db.commit()
    db.refresh(doc)
    write_audit(
        action=AuditAction.DOC_UPDATE, user=user, target_type="document", target_id=doc.id,
        detail={"rollback_to": version.version_label, "from_version_id": prev_id},
        request=request,
    )
    return _detail(db, doc)


@router.delete("/{doc_id}", status_code=status.HTTP_200_OK)
def delete_document(
    doc_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.DOC_DELETE)),
) -> dict:
    """软删除。物理文件与版本保留，由备份/清理任务统一处置。"""
    doc = get_document_or_404(db, doc_id)
    ensure_visible(user, doc)
    from app.services.documents import mark_deleted

    mark_deleted(doc, user)
    db.commit()
    write_audit(
        action=AuditAction.DOC_DELETE, user=user, target_type="document", target_id=doc.id,
        detail={"doc_no": doc.doc_no, "title": doc.title, "soft": True},
        request=request,
    )
    return {"ok": True, "message": "资料已移入回收状态，可由管理员恢复"}


@router.get("/{doc_id}/files", response_model=list[FileBrief])
def list_files(
    doc_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[FileBrief]:
    doc = get_document_or_404(db, doc_id)
    ensure_doc_access(db, user, doc)
    rows = db.scalars(
        select(FileObject).where(
            FileObject.document_id == doc_id, FileObject.status == "stored"
        ).order_by(FileObject.id)
    ).all()
    return [FileBrief.model_validate(r) for r in rows]


@router.get("/storage/usage", response_model=StorageUsage, include_in_schema=True)
def storage_usage(user: User = Depends(require_permission(Permission.SYSTEM_CONFIG))) -> StorageUsage:
    return StorageUsage(**storage.stat_usage())
