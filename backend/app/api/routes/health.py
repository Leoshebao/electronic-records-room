"""健康检查与系统信息接口（不需要认证）。"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    """存活探针：不依赖数据库，用于容器与 Nginx 健康检查。"""
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "env": settings.APP_ENV,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health/db")
def health_db(db: Session = Depends(get_db)) -> dict:
    """就绪探针：确认数据库连接与迁移状态。"""
    try:
        db.execute(text("SELECT 1"))
        version = db.execute(text("SHOW server_version")).scalar_one()
        return {"status": "ok", "database": "connected", "pg_version": version}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "database": "unavailable", "detail": str(exc)}


@router.get("/health/storage")
def health_storage() -> dict:
    """确认文件存储目录可写。"""
    root = settings.storage_path
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return {"status": "ok", "storage_root": str(root), "writable": True}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "storage_root": str(root), "detail": str(exc)}
