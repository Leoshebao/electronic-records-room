"""模型包入口：导入全部模型，确保 Alembic autogenerate 能感知。"""
from app.db.session import Base
from app.models.common import SoftDeleteMixin, TimestampMixin
from app.models.document import (
    Document,
    DocumentPermission,
    DocumentTag,
    DocumentVersion,
    FileObject,
    Tag,
)
from app.models.enums import (
    AuditAction,
    BorrowStatus,
    DocStatus,
    FileStatus,
    OCRStatus,
    Permission,
    Role,
    SecrecyLevel,
)
from app.models.room import Category, Room
from app.models.user import Department, User
from app.models.workflow import AuditLog, BackupRecord, BorrowRequest, OCRTask, SystemConfig

__all__ = [
    "Base",
    "TimestampMixin",
    "SoftDeleteMixin",
    # 主体
    "Department",
    "User",
    # 空间
    "Room",
    "Category",
    # 资料
    "Document",
    "DocumentVersion",
    "FileObject",
    "Tag",
    "DocumentTag",
    "DocumentPermission",
    # 流程
    "BorrowRequest",
    "OCRTask",
    "AuditLog",
    "SystemConfig",
    "BackupRecord",
    # 枚举
    "Role",
    "SecrecyLevel",
    "DocStatus",
    "FileStatus",
    "OCRStatus",
    "BorrowStatus",
    "AuditAction",
    "Permission",
]
