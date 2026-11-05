"""全文检索出入参模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.enums import SecrecyLevel
from app.schemas.document import DocumentBrief, PageMeta


class SearchHit(DocumentBrief):
    """检索命中项：在资料摘要字段基础上补充相关度、命中片段与命中字段。"""

    score: float | None = None
    snippet: str | None = None
    matched: list[str] = Field(default_factory=list, description="命中的字段名，如 title / search_text")


class SearchPage(BaseModel):
    items: list[SearchHit]
    meta: PageMeta
    query: str
    keywords: list[str] = Field(default_factory=list)
    took_ms: int
    trgm: bool = Field(description="是否启用 pg_trgm 索引加速")
    fts: bool = Field(default=False, description="是否走单字分词 GIN 全文索引")


class SuggestItem(BaseModel):
    id: int
    doc_no: str
    title: str
    secrecy_level: SecrecyLevel


class SearchStats(BaseModel):
    """检索模块自检：供运维确认索引是否生效。"""

    trgm: bool
    fts: bool = False
    indexes: list[str] = Field(default_factory=list)
    indexed_docs: int
    docs_total: int
