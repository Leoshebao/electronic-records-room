"""全文检索接口。

GET /api/search         关键词检索（多词 AND、相关度排序、片段高亮）
GET /api/search/suggest 题名 / 档号联想
GET /api/search/stats   检索模块自检（索引是否生效）
"""
from __future__ import annotations

import math
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.api.deps import get_db, level_filter_values, require_permission
from app.models.document import Document
from app.models.enums import AuditAction, Permission
from app.models.user import User
from app.schemas.document import PageMeta
from app.schemas.search import SearchPage, SearchStats, SuggestItem
from app.services import search as search_service
from app.services.audit import write_audit
from app.services.documents import sanity_level

router = APIRouter(prefix="/search", tags=["检索"])


@router.get("", response_model=SearchPage)
def search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=200, description="关键词，空格分隔多个"),
    room_id: int | None = None,
    category_id: int | None = None,
    secrecy_level: str | None = None,
    archive_year: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=50),
    sort: str = Query("relevance", pattern="^(relevance|created_at|updated_at|title|doc_no|archive_year)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.DOC_VIEW)),
) -> SearchPage:
    level = None
    if secrecy_level:
        level = sanity_level(secrecy_level)
        if level.value not in level_filter_values(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="该密级超出您的访问范围"
            )

    result = search_service.search_documents(
        db, user,
        q=q, page=page, size=size, sort=sort, order=order,
        room_id=room_id, category_id=category_id, secrecy_level=level,
        archive_year=archive_year, date_from=date_from, date_to=date_to,
    )

    write_audit(
        action=AuditAction.DOC_SEARCH, user=user, target_type="search",
        detail={
            "q": q[:200],
            "keywords": result["keywords"],
            "hits": result["total"],
            "took_ms": result["took_ms"],
        },
        request=request,
    )

    total = result["total"]
    return SearchPage(
        items=result["items"],
        meta=PageMeta(
            total=total, page=page, size=size,
            pages=math.ceil(total / size) if total else 0,
        ),
        query=q,
        keywords=result["keywords"],
        took_ms=result["took_ms"],
        trgm=result["trgm"],
        fts=result["fts"],
    )


@router.get("/suggest", response_model=list[SuggestItem])
def suggest(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(10, ge=1, le=20),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.DOC_VIEW)),
) -> list[SuggestItem]:
    return [SuggestItem(**row) for row in search_service.suggest(db, user, q, limit)]


@router.get("/stats", response_model=SearchStats)
def stats(
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.AUDIT_VIEW)),
) -> SearchStats:
    trgm = search_service.trgm_available(db)
    fts = search_service.fts_available(db)
    indexes: list[str] = []
    try:
        indexes = list(db.scalars(text(
            "select indexname from pg_indexes "
            "where schemaname = 'public' and indexname like 'ix\_doc\_%' "
            "order by indexname"
        )).all())
    except Exception:  # noqa: BLE001 - 非 PG 时无索引信息
        indexes = []
    indexed = db.scalar(
        select(func.count()).select_from(Document).where(
            Document.search_grams.is_not(None),
            Document.is_deleted.is_(False),
        )
    ) or 0
    total = db.scalar(
        select(func.count()).select_from(Document).where(Document.is_deleted.is_(False))
    ) or 0
    return SearchStats(trgm=trgm, fts=fts, indexes=indexes, indexed_docs=indexed, docs_total=total)
