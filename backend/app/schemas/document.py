"""资料与文件的出入参模型。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DocStatus, FileStatus, OCRStatus, SecrecyLevel


class FileBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    version_id: int | None = None
    original_name: str
    ext: str
    mime_type: str | None = None
    size_bytes: int
    page_count: int = 0
    status: FileStatus
    ocr_status: OCRStatus
    sha256: str | None = None
    created_at: datetime


class VersionBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    version_no: int
    version_label: str | None = None
    change_note: str | None = None
    is_current: bool
    created_by: int
    created_at: datetime


class DocumentBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    doc_no: str
    title: str
    room_id: int
    category_id: int | None = None
    secrecy_level: SecrecyLevel
    status: DocStatus
    summary: str | None = None
    keywords: str | None = None
    archive_year: int | None = None
    retention_years: int | None = None
    file_count: int = 0
    total_size: int = 0
    page_count: int = 0
    view_count: int = 0
    download_count: int = 0
    created_by: int
    created_at: datetime
    updated_at: datetime | None = None


class DocumentDetail(DocumentBrief):
    current_version_id: int | None = None
    responsible_dept_id: int | None = None
    files: list[FileBrief] = Field(default_factory=list)
    versions: list[VersionBrief] = Field(default_factory=list)


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    category_id: int | None = None
    secrecy_level: SecrecyLevel | None = None
    status: DocStatus | None = None
    summary: str | None = None
    keywords: str | None = Field(default=None, max_length=500)
    archive_year: int | None = None
    retention_years: int | None = None
    responsible_dept_id: int | None = None
    change_note: str | None = None


class PageMeta(BaseModel):
    total: int
    page: int
    size: int
    pages: int


class DocumentPage(BaseModel):
    items: list[DocumentBrief]
    meta: PageMeta


class StorageUsage(BaseModel):
    file_count: int
    total_bytes: int
    total_mb: float
    root: str
