"""借阅流程、OCR 任务、审计日志、系统配置、备份记录。"""
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models.common import TimestampMixin
from app.models.enums import BorrowStatus, OCRStatus


class BorrowRequest(Base, TimestampMixin):
    """借阅申请。到期未归由定时任务置为 expired 并收回权限。"""

    __tablename__ = "borrow_requests"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    request_no: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, index=True, comment="申请单号"
    )
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    applicant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False, comment="借阅事由")
    requested_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=7, server_default="7", comment="申请人期望借阅天数"
    )
    want_download: Mapped[bool] = mapped_column(
        default=False, nullable=False, server_default="false", comment="是否申请下载权"
    )
    want_print: Mapped[bool] = mapped_column(
        default=False, nullable=False, server_default="false", comment="是否申请打印权"
    )

    status: Mapped[BorrowStatus] = mapped_column(
        String(16), nullable=False, default=BorrowStatus.PENDING,
        server_default="pending", index=True,
    )
    approver_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="生效时间")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="应归还时间")
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    renew_count: Mapped[int] = mapped_column(default=0, nullable=False, server_default="0")

    __table_args__ = (
        Index("ix_borrow_status_due", "status", "due_at"),
        Index("ix_borrow_applicant_status", "applicant_id", "status"),
    )


class OCRTask(Base, TimestampMixin):
    """OCR 异步任务。worker 轮询 queued 记录并处理。"""

    __tablename__ = "ocr_tasks"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[OCRStatus] = mapped_column(
        String(16), nullable=False, default=OCRStatus.QUEUED,
        server_default="queued", index=True,
    )
    engine: Mapped[str] = mapped_column(String(32), nullable=False, default="paddleocr")
    retry_count: Mapped[int] = mapped_column(default=0, nullable=False, server_default="0")
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (Index("ix_ocrtask_status_created", "status", "created_at"),)


class AuditLog(Base):
    """审计日志。只增不改不删，独立于业务事务生命周期。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    username: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="冗余存储，防用户删除后丢失")
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="结构化明细")
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    result: Mapped[str] = mapped_column(String(16), nullable=False, default="success", server_default="success")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    __table_args__ = (
        Index("ix_audit_user_created", "user_id", "created_at"),
        Index("ix_audit_action_created", "action", "created_at"),
        Index("ix_audit_target", "target_type", "target_id"),
    )


class SystemConfig(Base, TimestampMixin):
    """系统参数。可在管理界面调整，避免改代码重启。"""

    __tablename__ = "system_configs"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="string", server_default="string",
        comment="string / int / bool / json",
    )
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_editable: Mapped[bool] = mapped_column(default=True, nullable=False, server_default="true")
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class BackupRecord(Base, TimestampMixin):
    """备份记录。full = 数据库 + 文件，db = 仅数据库，files = 仅文件。"""

    __tablename__ = "backup_records"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    backup_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="full", server_default="full"
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running", server_default="running")
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (Index("ix_backup_created", "created_at"),)
