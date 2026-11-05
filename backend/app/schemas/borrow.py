"""借阅模块请求 / 响应模型。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BorrowApplyIn(BaseModel):
    document_id: int = Field(..., ge=1, description="资料 ID")
    reason: str = Field(..., min_length=2, max_length=2000, description="借阅事由")
    days: int | None = Field(None, ge=1, le=90, description="期望借阅天数，默认 7")
    can_download: bool = Field(False, description="是否同时申请下载权")
    can_print: bool = Field(False, description="是否同时申请打印权")


class BorrowApproveIn(BaseModel):
    days: int | None = Field(None, ge=1, le=90, description="批准天数，缺省沿用申请天数")
    can_download: bool | None = Field(None, description="覆盖下载权，缺省沿用申请")
    can_print: bool | None = Field(None, description="覆盖打印权，缺省沿用申请")


class BorrowRejectIn(BaseModel):
    reason: str = Field(..., min_length=2, max_length=1000)


class BorrowRenewIn(BaseModel):
    days: int | None = Field(None, ge=1, le=90)


class BorrowBrief(BaseModel):
    id: int
    request_no: str
    document_id: int
    doc_no: str | None = None
    title: str | None = None
    secrecy_level: str | None = None
    applicant_id: int
    applicant_name: str | None = None
    reason: str
    status: str
    requested_days: int = 7
    want_download: bool = False
    want_print: bool = False
    approver_id: int | None = None
    approved_at: datetime | None = None
    reject_reason: str | None = None
    start_at: datetime | None = None
    due_at: datetime | None = None
    returned_at: datetime | None = None
    renew_count: int = 0
    remaining_days: int = 0
    created_at: datetime | None = None


class BorrowPage(BaseModel):
    items: list[BorrowBrief]
    total: int
    page: int
    size: int
    pages: int
    pending_total: int = 0


class SweepResult(BaseModel):
    expired: int = 0
    purged_permissions: int = 0
    request_nos: list[str] = []


class SweeperStatus(BaseModel):
    enabled: bool
    alive: bool
    interval: int = 60
    last_run: str | None = None
    last_result: dict = {}
