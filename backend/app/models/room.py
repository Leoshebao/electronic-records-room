"""资料室与类目树。"""
from sqlalchemy import BigInteger, ForeignKey, Identity, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.common import SoftDeleteMixin, TimestampMixin


class Room(Base, TimestampMixin, SoftDeleteMixin):
    """资料室：顶层容器，用于按业务条线隔离档案。"""

    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="资料室名称")
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, comment="资料室编码")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="存放位置，如 办公楼3层档案室"
    )
    keeper_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, comment="负责人"
    )
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, server_default="true")

    categories: Mapped[list["Category"]] = relationship(
        back_populates="room", cascade="all, delete-orphan"
    )


class Category(Base, TimestampMixin, SoftDeleteMixin):
    """类目树：最多三级，parent_id 自引用。path 形如 /1/5/9 便于子树查询。"""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    room_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("categories.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="类目名称")
    code: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="类目编码")
    path: Mapped[str] = mapped_column(String(500), nullable=False, default="/", comment="物化路径")
    level: Mapped[int] = mapped_column(default=1, nullable=False, server_default="1", comment="层级 1-3")
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, server_default="true")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    room: Mapped[Room] = relationship(back_populates="categories")
    children: Mapped[list["Category"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan"
    )
    parent: Mapped["Category | None"] = relationship(back_populates="children", remote_side="Category.id")

    __table_args__ = (
        UniqueConstraint("room_id", "parent_id", "name", name="uq_category_sibling_name"),
        Index("ix_categories_room_path", "room_id", "path"),
    )
