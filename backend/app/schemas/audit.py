"""审计日志查询相关模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None = None
    username: str | None = None
    action: str
    target_type: str | None = None
    target_id: int | None = None
    detail: dict[str, Any] | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    result: str
    created_at: datetime


class AuditPage(BaseModel):
    items: list[AuditOut]
    total: int
    page: int
    size: int


class AuditActionItem(BaseModel):
    action: str
    label: str
    count: int


class AuditSummary(BaseModel):
    total: int
    today: int
    failed: int
    by_action: list[AuditActionItem] = Field(default_factory=list)
    by_user: list[dict[str, Any]] = Field(default_factory=list)


class StatsOverview(BaseModel):
    documents: dict[str, Any]
    storage: dict[str, Any]
    borrow: dict[str, Any]
    ocr: dict[str, Any]
    users: dict[str, Any]
    trend: list[dict[str, Any]] = Field(default_factory=list)
    top_documents: list[dict[str, Any]] = Field(default_factory=list)


class BackupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    file_path: str
    backup_type: str
    size_bytes: int
    status: str
    error_msg: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None


class BackupList(BaseModel):
    items: list[BackupOut]
    total: int
    backup_root: str
    keep_days: int
