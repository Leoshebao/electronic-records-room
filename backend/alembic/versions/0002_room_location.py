"""rooms 增加 location 字段

Revision ID: 0002_room_location
Revises: 0001_initial
Create Date: 2026-10-29

注意：0001 用 Base.metadata.create_all() 建表，全新库建表时已带上当前 ORM 的
全部列（含 location）。本迁移必须幂等，否则新建库无法重放历史。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_room_location"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if _has_column("rooms", "location"):
        print("[0002] rooms.location 已存在，跳过")
        return
    op.add_column(
        "rooms",
        sa.Column("location", sa.String(length=200), nullable=True,
                  comment="存放位置，如 办公楼3层档案室"),
    )


def downgrade() -> None:
    if _has_column("rooms", "location"):
        op.drop_column("rooms", "location")
