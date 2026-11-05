"""认证接口：登录、登出、当前用户、修改密码。"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import build_user_brief, get_current_user
from app.core.config import settings
from app.core.security import (
    create_access_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.db.session import get_db
from app.models.enums import AuditAction
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    MessageResponse,
    TokenResponse,
    UserBrief,
)
from app.services.audit import client_ip, write_audit

logger = logging.getLogger("erecords.auth")
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(
        select(User).where(User.username == payload.username, User.is_deleted.is_(False))
    )

    # 统一错误提示，避免暴露用户名是否存在
    if user is None:
        write_audit(
            action=AuditAction.LOGIN_FAILED,
            username=payload.username,
            detail={"reason": "user_not_found"},
            request=request,
            result="failed",
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")

    now = datetime.now(timezone.utc)

    if user.locked_until and user.locked_until > now:
        remain = int((user.locked_until - now).total_seconds() // 60) + 1
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"账号已锁定，请 {remain} 分钟后重试",
        )

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用，请联系管理员")

    if not verify_password(payload.password, user.password_hash):
        user.failed_login_count += 1
        locked = False
        if user.failed_login_count >= settings.LOGIN_MAX_FAIL:
            user.locked_until = now + timedelta(minutes=settings.LOGIN_LOCK_MINUTES)
            user.failed_login_count = 0
            locked = True
        db.commit()
        write_audit(
            action=AuditAction.LOGIN_FAILED,
            user=user,
            detail={"reason": "bad_password", "locked": locked},
            request=request,
            result="failed",
        )
        detail = (
            f"密码错误次数过多，账号已锁定 {settings.LOGIN_LOCK_MINUTES} 分钟"
            if locked
            else f"用户名或密码错误，还可尝试 {settings.LOGIN_MAX_FAIL - user.failed_login_count} 次"
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)

    # 登录成功
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    user.last_login_ip = client_ip(request)
    db.commit()
    db.refresh(user)

    token, expires_in = create_access_token(
        user_id=user.id,
        username=user.username,
        role=user.role,
        token_version=user.token_version,
        must_change=user.must_change_password,
    )

    write_audit(action=AuditAction.LOGIN, user=user, request=request)

    return TokenResponse(
        access_token=token,
        expires_in=expires_in,
        must_change_password=user.must_change_password,
        user=UserBrief(**build_user_brief(user)),
    )


@router.post("/logout", response_model=MessageResponse)
def logout(
    request: Request,
    user: User = Depends(get_current_user),
) -> MessageResponse:
    # JWT 无状态，登出由前端丢弃 token；此处仅记录审计
    write_audit(action=AuditAction.LOGOUT, user=user, request=request)
    return MessageResponse(message="已退出登录")


@router.get("/me", response_model=UserBrief)
def me(user: User = Depends(get_current_user)) -> UserBrief:
    return UserBrief(**build_user_brief(user))


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MessageResponse:
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="原密码不正确")

    if payload.old_password == payload.new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码不能与原密码相同")

    err = validate_password_strength(payload.new_password)
    if err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)

    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    # 递增 token_version，使其它端已签发的 token 全部失效
    user.token_version += 1
    db.commit()

    write_audit(
        action=AuditAction.USER_UPDATE,
        user=user,
        target_type="user",
        target_id=user.id,
        detail={"field": "password", "self": True},
        request=request,
    )
    return MessageResponse(message="密码已修改，请使用新密码重新登录")


@router.get("/permission-matrix")
def permission_matrix(user: User = Depends(get_current_user)) -> dict:
    """返回三角色 × 四密级矩阵，供前端说明页展示。"""
    from app.core.permissions import LEVEL_LABELS, ROLE_MAX_LEVEL, permissions_of
    from app.models.enums import Role, SecrecyLevel

    matrix = []
    for role in Role:
        max_rank = ROLE_MAX_LEVEL[role]
        matrix.append(
            {
                "role": role.value,
                "levels": {
                    lv.value: lv.rank <= max_rank for lv in SecrecyLevel
                },
                "permissions": permissions_of(role),
            }
        )
    return {
        "levels": [{"value": lv.value, "label": LEVEL_LABELS[lv], "rank": lv.rank} for lv in SecrecyLevel],
        "matrix": matrix,
        "current_role": user.role,
    }
