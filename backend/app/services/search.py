"""中文全文检索服务。

设计要点：
1. 中文无词边界，PostgreSQL 内置分词器会把整句当一个词，故不用 tsvector，
   改用 pg_trgm 三元组 + ILIKE，GIN 索引可支撑万级档案的亚秒级检索。
2. 多关键词为 AND 语义：每个关键词都必须命中某个字段（题名 / 档号 / 摘要 /
   关键词 / 聚合正文），与用户「越搜越准」的直觉一致。
3. 相关度 = 字段权重 + 三元组相似度，题名命中权重最高。
4. 片段在服务端生成，关键词包 <em> 供前端高亮，内容做 HTML 转义防注入。
"""
from __future__ import annotations

import html
import re
import time

from sqlalchemy import Select, case, func, literal, or_, select, text
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.enums import SecrecyLevel
from app.models.room import Category
from app.models.user import User
from app.services.documents import visible_doc_query

MAX_KEYWORDS = 8
SNIPPET_RADIUS = 40
ESCAPE = "\\"

_SPLIT_RE = re.compile(r"[\s,，;；、|]+")


def split_keywords(q: str) -> list[str]:
    """按空格与中英文标点切分关键词，去重并限制数量，避免恶意长查询拖垮数据库。"""
    out: list[str] = []
    for part in _SPLIT_RE.split((q or "").strip()):
        part = part.strip()
        if not part or part in out:
            continue
        out.append(part)
        if len(out) >= MAX_KEYWORDS:
            break
    return out


def _escape_like(value: str) -> str:
    """转义 LIKE 通配符，防止用户输入的 % _ 变成通配。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def trgm_available(db: Session) -> bool:
    try:
        return bool(db.scalar(text("select 1 from pg_extension where extname = 'pg_trgm'")))
    except Exception:  # noqa: BLE001 - 非 PG 或权限不足时降级
        return False


# --------------------------------------------------------------------------
# 单字分词全文索引（不依赖 contrib，本机精简 PG 亦可用）
# --------------------------------------------------------------------------

# 英文/数字整词保留，中文逐字切开
_TOKEN_RE = re.compile(r"[0-9A-Za-z]+|[\u4e00-\u9fff]")
GRAMS_INDEX = "ix_doc_search_grams_gin"


def make_grams(value: str | None) -> str:
    """把文本转成空格分隔的检索 token 串：中文逐字、英文整词，均小写。"""
    if not value:
        return ""
    return " ".join(t.lower() for t in _TOKEN_RE.findall(value))


def make_tsquery(keyword: str) -> str:
    """相邻 token 用 <-> 连成短语，保证词序连续，避免「工」「竣」跨位置误命中。"""
    tokens = [t.lower() for t in _TOKEN_RE.findall(keyword or "")]
    if not tokens:
        return ""
    return " <-> ".join(tokens)


def fts_available(db: Session) -> bool:
    """GIN 索引存在即视为可用；索引缺失时降级 ILIKE。"""
    try:
        return bool(db.scalar(text(f"select to_regclass('public.{GRAMS_INDEX}')")))
    except Exception:  # noqa: BLE001
        return False


def _fts_match(keyword: str):
    vector = func.to_tsvector("simple", func.coalesce(Document.search_grams, ""))
    return vector.op("@@")(func.to_tsquery("simple", make_tsquery(keyword)))


def _like(value: str) -> str:
    return f"%{_escape_like(value)}%"


def _field_match_any(keywords: list[str], column):
    return or_(*[column.ilike(_like(k), escape=ESCAPE) for k in keywords])


def _score_expr(keywords: list[str], full: str, trgm: bool):
    """字段权重 + 三元组相似度；trgm 不可用时仅用字段权重。"""
    score = (
        case((_field_match_any(keywords, Document.title), 5.0), else_=0.0)
        + case((_field_match_any(keywords, Document.doc_no), 3.0), else_=0.0)
        + case((_field_match_any(keywords, func.coalesce(Document.keywords, "")), 2.0), else_=0.0)
        + case((_field_match_any(keywords, func.coalesce(Document.summary, "")), 1.5), else_=0.0)
        + case((_field_match_any(keywords, func.coalesce(Document.search_text, "")), 1.0), else_=0.0)
    )
    if trgm and full:
        score = score + func.similarity(func.coalesce(Document.search_text, ""), full)
    return score.label("score")


def _apply_category(db: Session, stmt: Select, category_id: int) -> Select:
    """类目过滤含整棵子树。"""
    cat = db.get(Category, category_id)
    if cat is None or cat.is_deleted:
        return stmt.where(Document.category_id == -1)
    sub_ids = db.scalars(
        select(Category.id).where(
            Category.room_id == cat.room_id,
            Category.path.like(f"{cat.path}%"),
            Category.is_deleted.is_(False),
        )
    ).all()
    return stmt.where(Document.category_id.in_(list(sub_ids) or [-1]))


def _matched_fields(doc: Document, keywords: list[str]) -> list[str]:
    fields = {
        "title": doc.title or "",
        "doc_no": doc.doc_no or "",
        "summary": doc.summary or "",
        "keywords": doc.keywords or "",
        "search_text": doc.search_text or "",
    }
    hit: list[str] = []
    for name, value in fields.items():
        low = value.lower()
        if any(k.lower() in low for k in keywords):
            hit.append(name)
    return hit


def make_snippet(doc: Document, keywords: list[str]) -> str | None:
    """截取首个命中位置附近片段并高亮关键词。"""
    source = doc.search_text or " ".join(p for p in (doc.summary, doc.keywords) if p)
    if not source:
        return None
    low = source.lower()
    pos, hit_word = -1, ""
    for k in keywords:
        idx = low.find(k.lower())
        if idx >= 0 and (pos < 0 or idx < pos):
            pos, hit_word = idx, k
    if pos < 0:
        return html.escape(source[: SNIPPET_RADIUS * 2]) + "…"

    start = max(0, pos - SNIPPET_RADIUS)
    end = min(len(source), pos + len(hit_word) + SNIPPET_RADIUS)
    fragment = html.escape(source[start:end])
    for k in keywords:
        pattern = re.compile(re.escape(html.escape(k)), re.IGNORECASE)
        fragment = pattern.sub(lambda m: f"<em>{m.group(0)}</em>", fragment)
    return ("…" if start > 0 else "") + fragment + ("…" if end < len(source) else "")


def search_documents(
    db: Session,
    user: User,
    *,
    q: str,
    page: int = 1,
    size: int = 20,
    sort: str = "relevance",
    order: str = "desc",
    room_id: int | None = None,
    category_id: int | None = None,
    secrecy_level: SecrecyLevel | None = None,
    archive_year: int | None = None,
    date_from: object | None = None,
    date_to: object | None = None,
) -> dict:
    started = time.perf_counter()
    keywords = split_keywords(q)
    trgm = trgm_available(db)
    full = " ".join(keywords)

    stmt = visible_doc_query(user, db)
    if room_id:
        stmt = stmt.where(Document.room_id == room_id)
    if category_id:
        stmt = _apply_category(db, stmt, category_id)
    if secrecy_level is not None:
        stmt = stmt.where(Document.secrecy_level == secrecy_level)
    if archive_year:
        stmt = stmt.where(Document.archive_year == archive_year)
    if date_from is not None:
        stmt = stmt.where(Document.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Document.created_at <= date_to)

    # 多关键词 AND：每个词都要命中。优先走 GIN 全文索引，索引缺失时降级 ILIKE。
    use_fts = fts_available(db) if keywords else False
    for kw in keywords:
        if use_fts and make_tsquery(kw):
            stmt = stmt.where(_fts_match(kw))
            continue
        like = _like(kw)
        stmt = stmt.where(or_(
            Document.title.ilike(like, escape=ESCAPE),
            Document.doc_no.ilike(like, escape=ESCAPE),
            Document.summary.ilike(like, escape=ESCAPE),
            Document.keywords.ilike(like, escape=ESCAPE),
            Document.search_text.ilike(like, escape=ESCAPE),
        ))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    score_col = _score_expr(keywords, full, trgm) if keywords else literal(0.0).label("score")
    stmt = stmt.add_columns(score_col)

    if sort == "relevance" and keywords:
        if order == "asc":
            stmt = stmt.order_by(score_col.asc(), Document.created_at.desc())
        else:
            stmt = stmt.order_by(score_col.desc(), Document.created_at.desc())
    else:
        column = {
            "created_at": Document.created_at,
            "updated_at": Document.updated_at,
            "title": Document.title,
            "doc_no": Document.doc_no,
            "archive_year": Document.archive_year,
        }.get(sort, Document.created_at)
        stmt = stmt.order_by(column.desc() if order == "desc" else column.asc(), Document.id.desc())

    rows = db.execute(stmt.offset((page - 1) * size).limit(size)).all()

    items: list[dict] = []
    for doc, score in rows:
        payload = {
            "id": doc.id,
            "doc_no": doc.doc_no,
            "title": doc.title,
            "room_id": doc.room_id,
            "category_id": doc.category_id,
            "secrecy_level": doc.secrecy_level,
            "status": doc.status,
            "summary": doc.summary,
            "keywords": doc.keywords,
            "archive_year": doc.archive_year,
            "retention_years": doc.retention_years,
            "file_count": doc.file_count or 0,
            "total_size": doc.total_size or 0,
            "page_count": doc.page_count or 0,
            "view_count": doc.view_count or 0,
            "download_count": doc.download_count or 0,
            "created_by": doc.created_by,
            "created_at": doc.created_at,
            "updated_at": doc.updated_at,
            "score": round(float(score or 0), 4),
            "snippet": make_snippet(doc, keywords),
            "matched": _matched_fields(doc, keywords),
        }
        items.append(payload)

    took_ms = max(1, int((time.perf_counter() - started) * 1000))
    return {
        "items": items,
        "total": total,
        "took_ms": took_ms,
        "keywords": keywords,
        "trgm": trgm,
        "fts": use_fts,
    }


def suggest(db: Session, user: User, q: str, limit: int = 10) -> list[dict]:
    """题名 / 档号联想，走同一条密级可见性口径，避免联想泄露越权资料。"""
    like = _like(q.strip())
    if not like or like == "%%":
        return []
    stmt = (
        visible_doc_query(user, db)
        .where(or_(
            Document.title.ilike(like, escape=ESCAPE),
            Document.doc_no.ilike(like, escape=ESCAPE),
        ))
        .order_by(Document.created_at.desc())
        .limit(max(1, min(limit, 20)))
    )
    rows = db.scalars(stmt).all()
    return [
        {"id": r.id, "doc_no": r.doc_no, "title": r.title, "secrecy_level": r.secrecy_level}
        for r in rows
    ]
