"""检索索引：pg_trgm 扩展与 GIN 三元组索引

Revision ID: 0003_search_index
Revises: 0002_room_location
Create Date: 2026-10-29

中文没有词边界，PostgreSQL 内置 tsvector 分词对中文无效，
因此检索走 pg_trgm 三元组 + ILIKE，由 GIN 索引加速（万级档案毫秒级返回）。
若数据库无权限安装扩展，迁移自动跳过索引，检索退化为顺序扫描但不影响功能。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_search_index"
down_revision: Union[str, None] = "0002_room_location"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEXES: list[tuple[str, str, str]] = [
    ("ix_doc_search_trgm", "documents", "search_text"),
    ("ix_doc_title_trgm", "documents", "title"),
    ("ix_doc_no_trgm", "documents", "doc_no"),
    ("ix_file_ocr_trgm", "files", "ocr_text"),
]


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    trgm = True
    try:
        with conn.begin_nested():
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    except Exception:  # noqa: BLE001 - 无权限时降级
        trgm = False
    if not trgm:
        print("[0003] pg_trgm 不可用，跳过 GIN 索引（检索退化为顺序扫描）")
        return
    for name, table, column in INDEXES:
        with conn.begin_nested():
            conn.execute(sa.text(
                f"CREATE INDEX IF NOT EXISTS {name} ON {table} USING gin ({column} gin_trgm_ops)"
            ))


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    for name, _table, _column in INDEXES:
        with conn.begin_nested():
            conn.execute(sa.text(f"DROP INDEX IF EXISTS {name}"))
