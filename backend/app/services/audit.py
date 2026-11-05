"""审计日志写入。使用独立 session，避免业务事务回滚导致审计丢失。"""
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.enums import AuditAction
from app.models.user import User
from app.models.workflow import AuditLog

logger = logging.getLogger("erecords.audit")


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    # Nginx 反代后真实 IP 在 X-Forwarded-For 首位
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else None


def write_audit(
    *,
    action: AuditAction | str,
    user: User | None = None,
    user_id: int | None = None,
    username: str | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    detail: dict[str, Any] | None = None,
    request: Request | None = None,
    result: str = "success",
    db: Session | None = None,
) -> None:
    """写一条审计。审计失败只记录日志，绝不影响主流程。"""
    payload = AuditLog(
        user_id=user.id if user else user_id,
        username=user.username if user else username,
        action=action.value if isinstance(action, AuditAction) else action,
        target_type=target_type,
        target_id=target_id,
        detail=detail,
        ip_address=client_ip(request),
        user_agent=(request.headers.get("user-agent", "")[:500] if request else None),
        result=result,
        created_at=datetime.now(timezone.utc),
    )
    if db is not None:
        try:
            db.add(payload)
            db.flush()
        except Exception:  # noqa: BLE001
            logger.exception("审计写入失败(同事务)")
        return

    own_session = SessionLocal()
    try:
        own_session.add(payload)
        own_session.commit()
    except Exception:  # noqa: BLE001
        own_session.rollback()
        logger.exception("审计写入失败(独立事务)")
    finally:
        own_session.close()
