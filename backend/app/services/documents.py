"""资料业务服务：档号生成、密级校验、检索文本聚合、版本管理。"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import Integer, cast, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import level_filter_values
from app.core.permissions import can_access_level
from app.models.document import Document, DocumentPermission, DocumentVersion, FileObject
from app.models.enums import DocStatus, SecrecyLevel
from app.models.room import Room
from app.models.user import User

logger = logging.getLogger(__name__)


def generate_doc_no(db: Session, room: Room, year: int | None = None) -> str:
    """档号 = 资料室编码-年度-四位流水号，如 DA-2026-0001。"""
    year = year or datetime.now().year
    prefix = f"{room.code}-{year}-"
    last_seq = db.scalar(
        select(func.max(cast(func.right(Document.doc_no, 4), Integer))).where(
            Document.doc_no.like(f"{prefix}%")
        )
    )
    seq = (last_seq or 0) + 1
    if seq > 9999:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{room.code} 在 {year} 年的档号已用尽（上限 9999 份）",
        )
    return f"{prefix}{seq:04d}"


def get_room_or_404(db: Session, room_id: int) -> Room:
    room = db.get(Room, room_id)
    if room is None or room.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料室不存在")
    return room


def get_document_or_404(db: Session, doc_id: int) -> Document:
    doc = db.get(Document, doc_id)
    if doc is None or doc.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料不存在")
    return doc


def ensure_visible(user: User, doc: Document) -> None:
    """密级可见性校验（写操作路径使用，不接受临时授权越级）。"""
    if not can_access_level(user.role, doc.secrecy_level):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该资料密级超出您的访问范围")


def ensure_doc_access(db: Session, user: User, doc: Document, need: str = "view") -> None:
    """读取路径的访问校验：密级矩阵优先，其次看借阅/额外授权是否放行。

    need: view / download / print —— 对应授权位；授权放行后仍受密级矩阵约束的写操作不走本函数。
    """
    if can_access_level(user.role, doc.secrecy_level):
        return
    perm = db.scalar(
        select(DocumentPermission).where(
            DocumentPermission.document_id == doc.id,
            DocumentPermission.subject_type == "user",
            DocumentPermission.subject_id == user.id,
            or_(
                DocumentPermission.expires_at.is_(None),
                DocumentPermission.expires_at > datetime.now(),
            ),
        )
    )
    if perm is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该资料密级超出您的访问范围")

    allowed = {
        "view": perm.can_view,
        "download": perm.can_download,
        "print": perm.can_print,
    }.get(need, False)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"您对该资料没有{ {'view': '查看', 'download': '下载', 'print': '打印'}.get(need, '') }权限",
        )


def visible_doc_query(user: User, db: Session):
    """按角色密级矩阵过滤的查询底座。"""
    return select(Document).where(
        Document.is_deleted.is_(False),
        Document.secrecy_level.in_(level_filter_values(user)),
    )


def granted_doc_ids(db: Session, user: User) -> list[int]:
    """额外授权的资料 ID（部门 / 角色 / 个人三类主体）。"""
    rows = db.scalars(
        select(DocumentPermission.document_id).where(
            DocumentPermission.can_view.is_(True),
            or_(
                (DocumentPermission.subject_type == "user")
                & (DocumentPermission.subject_id == user.id),
                (DocumentPermission.subject_type == "role")
                & (DocumentPermission.subject_id == _role_ordinal(user.role)),
                (DocumentPermission.subject_type == "department")
                & (DocumentPermission.subject_id == (user.department_id or -1)),
            ),
            or_(
                DocumentPermission.expires_at.is_(None),
                DocumentPermission.expires_at > datetime.now(),
            ),
        )
    ).all()
    return list(rows)


def _role_ordinal(role: str) -> int:
    from app.models.enums import Role

    order = {Role.SYSADMIN.value: 1, Role.RECORDS_MANAGER.value: 2, Role.VIEWER.value: 3}
    return order.get(str(role), 0)


def refresh_search_text(db: Session, doc: Document) -> None:
    """聚合标题 / 摘要 / 关键词 / OCR 文本，供全文检索使用。"""
    # autoflush=False：先把文件 OCR 文本落盘，否则聚合读到旧的 NULL
    db.flush()
    parts: list[str] = [doc.title or "", doc.summary or "", doc.keywords or "", doc.doc_no or ""]
    ocr_rows = db.scalars(
        select(FileObject.ocr_text).where(
            FileObject.document_id == doc.id,
            FileObject.ocr_text.is_not(None),
        )
    ).all()
    parts.extend(t for t in ocr_rows if t)
    doc.search_text = "\n".join(p for p in parts if p).strip()[:200000] or None
    # 同源生成单字分词列，保证 search_text 与 search_grams 永不脱节
    from app.services.search import make_grams

    doc.search_grams = make_grams(doc.search_text) or None


def next_version(db: Session, doc: Document) -> tuple[int, str]:
    max_no = db.scalar(
        select(func.max(DocumentVersion.version_no)).where(
            DocumentVersion.document_id == doc.id
        )
    ) or 0
    no = max_no + 1
    return no, f"V{no}.0"


def recalc_doc_stats(db: Session, doc: Document) -> None:
    rows = db.scalars(
        select(FileObject).where(
            FileObject.document_id == doc.id,
            FileObject.status == "stored",
        )
    ).all()
    doc.file_count = len(rows)
    doc.total_size = sum(r.size_bytes or 0 for r in rows)
    doc.page_count = sum(r.page_count or 0 for r in rows)


def mark_deleted(doc: Document, user: User) -> None:
    """软删除：只打标记，物理文件与版本保留，便于误删恢复与审计追溯。"""
    doc.is_deleted = True
    doc.deleted_at = datetime.now()
    doc.deleted_by = user.id


def sanity_level(value: str | SecrecyLevel) -> SecrecyLevel:
    try:
        return SecrecyLevel(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"非法密级：{value}"
        ) from None
