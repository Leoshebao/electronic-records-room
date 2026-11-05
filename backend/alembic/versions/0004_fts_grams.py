"""单字分词全文索引：search_grams + GIN(tsvector)

Revision ID: 0004_fts_grams
Revises: 0003_search_index
Create Date: 2026-10-29

背景：本地/精简部署的 PostgreSQL 可能没有 contrib（pg_trgm 不可用），
而中文又无词边界，内置分词器无法切词。此处采用工程界通行的「单字分词」变通：
写入时把中文逐字拆开、英文保留整词，以空格连接存入 search_grams 列；
索引与查询都用 to_tsvector('simple', ...)，中文检索用短语查询（<->）保证词序连续，
等价于子串匹配但能吃到 GIN 索引。

该列由 app.services.documents.refresh_search_text 维护，
历史数据由 scripts/rebuild_search_index.py 回填。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_fts_grams"
down_revision: Union[str, None] = "0003_search_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

IDX = "ix_doc_search_grams_gin"
VEC = "to_tsvector('simple', coalesce(search_grams, ''))"


def _has_column(table: str, column: str) -> bool:
    """0001 用 create_all 建表，全新库可能已含该列，故需幂等。"""
    insp = sa.inspect(op.get_bind())
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if _has_column("documents", "search_grams"):
        print("[0004] documents.search_grams 已存在，跳过加列")
    else:
        op.add_column("documents", sa.Column("search_grams", sa.Text(), nullable=True))
    conn = op.get_bind()
    try:
        conn.execute(sa.text(
            f"CREATE INDEX IF NOT EXISTS {IDX} ON documents USING gin ({VEC})"
        ))
    except Exception as exc:  # noqa: BLE001
        print(f"[0004] GIN 索引创建失败，检索退化为 ILIKE 顺序扫描：{exc}")


def downgrade() -> None:
    op.execute(sa.text(f"DROP INDEX IF EXISTS {IDX}"))
    op.drop_column("documents", "search_grams")
