"""初始建表：15 张业务表 + 审计防篡改触发器 + 可选的 pg_trgm 全文索引

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-29

说明：
1. 建表直接由 ORM 元数据生成，保证与 app/models 零漂移；
2. 后续结构性变更请使用 `alembic revision --autogenerate`；
3. pg_trgm 属 contrib 扩展，部分精简发行包缺失，故按可用性条件创建索引。
"""
from typing import Sequence, Union

from alembic import op

from app.db.session import Base
import app.models  # noqa: F401  必须导入以注册元数据

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    # 建表顺序由 SQLAlchemy 依据外键依赖自动排序
    Base.metadata.create_all(bind=bind)

    # ---- 模糊检索增强：pg_trgm 可用则建 GIN 索引，不可用则静默跳过 ----
    op.execute(
        """
        DO $$
        BEGIN
            CREATE EXTENSION IF NOT EXISTS pg_trgm;
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'pg_trgm 扩展不可用，检索将退回 ILIKE 模式';
        END;
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
                CREATE INDEX IF NOT EXISTS ix_documents_search_trgm
                    ON documents USING gin (search_text gin_trgm_ops);
                CREATE INDEX IF NOT EXISTS ix_documents_title_trgm
                    ON documents USING gin (title gin_trgm_ops);
            END IF;
        END;
        $$;
        """
    )

    # ---- 审计日志防篡改：禁止 UPDATE / DELETE，只允许 INSERT 与查询 ----
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_audit_modify() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '审计日志不允许修改或删除';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_audit_no_update
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION prevent_audit_modify();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    op.execute("DROP TRIGGER IF EXISTS trg_audit_no_update ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_modify()")
    Base.metadata.drop_all(bind=bind)
