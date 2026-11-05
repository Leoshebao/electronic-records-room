"""模型公共基类与混入。"""
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="更新时间",
    )


class SoftDeleteMixin:
    """软删除：业务表一律不做物理删除。"""

    is_deleted: Mapped[bool] = mapped_column(
        default=False, nullable=False, index=True, comment="是否已删除"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="删除时间"
    )
    deleted_by: Mapped[int | None] = mapped_column(nullable=True, comment="删除人ID")


__all__ = ["Base", "TimestampMixin", "SoftDeleteMixin"]
