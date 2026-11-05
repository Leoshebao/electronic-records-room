"""用户、部门。"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.common import SoftDeleteMixin, TimestampMixin
from app.models.enums import Role


class Department(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="部门名称")
    code: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True, comment="部门编码")
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, server_default="true")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    users: Mapped[list["User"]] = relationship(back_populates="department")

    __table_args__ = (Index("ix_departments_parent_sort", "parent_id", "sort_order"),)


class User(Base, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    username: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True, comment="登录名"
    )
    full_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="姓名")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, comment="bcrypt 哈希")
    role: Mapped[Role] = mapped_column(
        String(32), nullable=False, default=Role.VIEWER, server_default="viewer", comment="角色"
    )
    department_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        default=True, nullable=False, server_default="true", comment="是否启用"
    )
    must_change_password: Mapped[bool] = mapped_column(
        default=True, nullable=False, server_default="true", comment="首次登录需改密"
    )

    # 登录安全
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failed_login_count: Mapped[int] = mapped_column(
        default=0, nullable=False, server_default="0", comment="连续失败次数"
    )
    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="锁定截止时间"
    )
    # 会话失效水位：改密后强制旧 token 失效
    token_version: Mapped[int] = mapped_column(default=1, nullable=False, server_default="1")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    department: Mapped[Department | None] = relationship(back_populates="users")

    @property
    def department_name(self) -> str | None:
        return self.department.name if self.department else None

    @property
    def role_label(self) -> str:
        return {
            "sysadmin": "系统管理员",
            "records_manager": "档案管理员",
            "viewer": "查阅者",
        }.get(self.role, self.role)

    __table_args__ = (
        Index("ix_users_role_active", "role", "is_active"),
        Index("ix_users_dept_active", "department_id", "is_active"),
    )
