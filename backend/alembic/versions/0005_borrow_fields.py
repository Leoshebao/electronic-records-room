"""借阅申请补充期望天数与权限位

Revision ID: 0005_borrow_fields
Revises: 0004_fts_grams
Create Date: 2026-10-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_borrow_fields"
down_revision = "0004_fts_grams"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    """0001 用 create_all 建表，全新库可能已含这些列，故需幂等。"""
    insp = sa.inspect(op.get_bind())
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if not _has_column("borrow_requests", "requested_days"):
        op.add_column(
            "borrow_requests",
            sa.Column("requested_days", sa.Integer(), nullable=False, server_default="7",
                      comment="申请人期望借阅天数"),
        )
    if not _has_column("borrow_requests", "want_download"):
        op.add_column(
            "borrow_requests",
            sa.Column("want_download", sa.Boolean(), nullable=False, server_default=sa.text("false"),
                      comment="是否申请下载权"),
        )
    if not _has_column("borrow_requests", "want_print"):
        op.add_column(
            "borrow_requests",
            sa.Column("want_print", sa.Boolean(), nullable=False, server_default=sa.text("false"),
                      comment="是否申请打印权"),
        )


def downgrade() -> None:
    op.drop_column("borrow_requests", "want_print")
    op.drop_column("borrow_requests", "want_download")
    op.drop_column("borrow_requests", "requested_days")
