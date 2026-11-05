"""资料主表、版本、物理文件、标签、细粒度授权。"""
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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.common import SoftDeleteMixin, TimestampMixin
from app.models.enums import DocStatus, FileStatus, OCRStatus, SecrecyLevel


class Document(Base, TimestampMixin, SoftDeleteMixin):
    """资料主表。一条记录代表一份档案，可有多个版本与多个物理文件。"""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    doc_no: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True, comment="档号"
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False, comment="题名")
    room_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("rooms.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    secrecy_level: Mapped[SecrecyLevel] = mapped_column(
        String(16), nullable=False, default=SecrecyLevel.INTERNAL,
        server_default="internal", comment="密级",
    )
    status: Mapped[DocStatus] = mapped_column(
        String(16), nullable=False, default=DocStatus.ACTIVE,
        server_default="active", comment="状态", index=True,
    )

    summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="摘要")
    keywords: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="关键词，逗号分隔")

    responsible_dept_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("departments.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    current_version_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("document_versions.id", ondelete="SET NULL", use_alter=True,
                   name="fk_documents_current_version"),
        nullable=True,
    )
    file_count: Mapped[int] = mapped_column(default=0, nullable=False, server_default="0")
    total_size: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False, server_default="0", comment="字节"
    )
    page_count: Mapped[int] = mapped_column(default=0, nullable=False, server_default="0")

    view_count: Mapped[int] = mapped_column(default=0, nullable=False, server_default="0")
    download_count: Mapped[int] = mapped_column(default=0, nullable=False, server_default="0")

    # 全文检索聚合文本（标题 + 摘要 + 关键词 + 所有文件 OCR 结果），配合 pg_trgm GIN 索引
    search_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 单字分词写入的检索列：中文逐字、英文整词，空格分隔。
    # 供 to_tsvector('simple', ...) + GIN 索引使用，弥补 PostgreSQL 无中文分词的缺口。
    search_grams: Mapped[str | None] = mapped_column(Text, nullable=True)

    archive_year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    retention_years: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="保管期限（年），NULL 表示永久"
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    versions: Mapped[list["DocumentVersion"]] = relationship(
        back_populates="document", cascade="all, delete-orphan",
        foreign_keys="DocumentVersion.document_id", order_by="DocumentVersion.version_no",
    )
    files: Mapped[list["FileObject"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    tags: Mapped[list["DocumentTag"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_documents_room_cat_status", "room_id", "category_id", "status"),
        Index("ix_documents_level_status", "secrecy_level", "status"),
        # 说明：search_text / title 的 pg_trgm GIN 索引不在 ORM 元数据中声明，
        # 因为 pg_trgm 属于 PostgreSQL contrib 扩展，精简版发行包可能缺失。
        # 该索引由迁移 0001_initial 在检测到扩展可用时条件创建，缺失时检索退回 ILIKE，
        # 10-30 人局域网规模（万级数据量）性能完全可接受。
    )


class DocumentVersion(Base, TimestampMixin):
    """版本记录。V1 为首次入库，后续每次内容变更递增。"""

    __tablename__ = "document_versions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_no: Mapped[int] = mapped_column(default=1, nullable=False, comment="版本序号")
    version_label: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="如 V1.0")
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="变更说明")
    is_current: Mapped[bool] = mapped_column(default=True, nullable=False, server_default="true")
    created_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    document: Mapped[Document] = relationship(
        back_populates="versions", foreign_keys=[document_id]
    )
    files: Mapped[list["FileObject"]] = relationship(back_populates="version")

    __table_args__ = (
        UniqueConstraint("document_id", "version_no", name="uq_version_doc_no"),
    )


class FileObject(Base, TimestampMixin):
    """物理文件。落盘名使用 UUID，原始文件名仅存数据库，避免路径注入与乱码。"""

    __tablename__ = "files"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True
    )
    original_name: Mapped[str] = mapped_column(String(500), nullable=False, comment="原始文件名")
    stored_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="UUID 文件名")
    rel_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="相对 storage 的路径")
    ext: Mapped[str] = mapped_column(String(20), nullable=False, comment="小写扩展名不含点")
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False, server_default="0")
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True, comment="用于秒传与去重")
    page_count: Mapped[int] = mapped_column(default=0, nullable=False, server_default="0")

    status: Mapped[FileStatus] = mapped_column(
        String(16), nullable=False, default=FileStatus.STORED, server_default="stored"
    )
    ocr_status: Mapped[OCRStatus] = mapped_column(
        String(16), nullable=False, default=OCRStatus.QUEUED,
        server_default="queued", index=True, comment="OCR 状态",
    )
    ocr_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="OCR 提取文本")

    created_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    document: Mapped[Document] = relationship(back_populates="files")
    version: Mapped[DocumentVersion | None] = relationship(back_populates="files")

    __table_args__ = (
        Index("ix_files_doc_status", "document_id", "status"),
        # ix_files_ocr_status 已由 ocr_status 列的 index=True 自动创建，此处不可重复声明
    )


class Tag(Base, TimestampMixin):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True, comment="前端展示色")
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class DocumentTag(Base):
    """资料与标签多对多。"""

    __tablename__ = "document_tags"

    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )

    document: Mapped[Document] = relationship(back_populates="tags")
    tag: Mapped[Tag] = relationship()


class DocumentPermission(Base, TimestampMixin):
    """细粒度授权：在角色密级矩阵之外，对单份资料额外放行或禁止。"""

    __tablename__ = "document_permissions"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_type: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="user / department / role"
    )
    subject_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="对应主体 ID")
    can_view: Mapped[bool] = mapped_column(default=True, nullable=False, server_default="true")
    can_download: Mapped[bool] = mapped_column(default=False, nullable=False, server_default="false")
    can_print: Mapped[bool] = mapped_column(default=False, nullable=False, server_default="false")
    granted_by: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("document_id", "subject_type", "subject_id", name="uq_docperm_subject"),
    )
