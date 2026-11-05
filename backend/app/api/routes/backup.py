"""备份管理路由：触发备份、查看记录、下载备份包、清理过期备份。"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.api.deps import require_permission
from app.models.enums import Permission
from app.db.session import get_db
from app.models.enums import AuditAction
from app.models.user import User
from app.models.workflow import BackupRecord
from app.schemas.audit import BackupList, BackupOut
from app.services.audit import write_audit
from app.services.backup import cleanup_old_backups, run_backup

router = APIRouter()


@router.get("", response_model=BackupList, summary="备份记录列表")
def list_backups(
    limit: int = 50,
    db: Session = Depends(get_db),
    _user: User = Depends(require_permission(Permission.BACKUP_MANAGE)),
) -> BackupList:
    total = db.scalar(select(func.count()).select_from(BackupRecord)) or 0
    rows = db.scalars(
        select(BackupRecord).order_by(BackupRecord.created_at.desc()).limit(max(1, min(limit, 200)))
    ).all()
    return BackupList(
        items=[BackupOut.model_validate(r) for r in rows],
        total=total,
        backup_root=str(settings.backup_path),
        keep_days=settings.BACKUP_KEEP_DAYS,
    )


@router.post("", response_model=BackupOut, status_code=status.HTTP_201_CREATED, summary="立即备份")
def create_backup(
    request: Request,
    backup_type: str = "full",
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.BACKUP_MANAGE)),
) -> BackupOut:
    if backup_type not in {"full", "db", "files"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="备份类型仅支持 full / db / files")
    record = run_backup(db, backup_type=backup_type, created_by=user.id)
    write_audit(
        action=AuditAction.BACKUP, user=user, target_type="backup", target_id=record.id,
        detail={"type": backup_type, "status": record.status, "size": record.size_bytes,
                "file": record.filename, "note": record.error_msg},
        request=request,
    )
    if record.status != "success":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"备份失败：{record.error_msg or '未知错误'}",
        )
    return BackupOut.model_validate(record)


@router.get("/{backup_id}/download", summary="下载备份包")
def download_backup(
    backup_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.BACKUP_MANAGE)),
):
    record = db.get(BackupRecord, backup_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="备份记录不存在")
    path = Path(record.file_path) if record.file_path else None
    # 便携版兼容：整个目录拷贝到其他电脑后，历史记录里的绝对路径会失效或越界，
    # 此处按文件名在当前备份目录内回退查找
    inside = False
    if path is not None:
        try:
            inside = settings.backup_path in path.resolve().parents
        except OSError:
            inside = False
    if path is None or not inside or not path.exists():
        alt = Path(settings.backup_path) / record.filename
        if alt.exists():
            path = alt
    if not path or not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="备份文件已不存在")
    # 防越界：只允许下载备份目录内的文件
    if settings.backup_path not in path.resolve().parents:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="非法的备份路径")
    write_audit(
        action=AuditAction.BACKUP, user=user, target_type="backup", target_id=record.id,
        detail={"action": "download", "file": record.filename}, request=request,
    )
    return FileResponse(path, filename=record.filename, media_type="application/zip")


@router.delete("/cleanup", summary="清理过期备份")
def cleanup(
    request: Request,
    keep_days: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission(Permission.BACKUP_MANAGE)),
) -> dict:
    result = cleanup_old_backups(db, keep_days)
    write_audit(
        action=AuditAction.BACKUP, user=user, target_type="backup",
        detail={"action": "cleanup", **result}, request=request,
    )
    return {"ok": True, **result}
