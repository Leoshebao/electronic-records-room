"""依赖注入：当前用户、权限校验、密级过滤。"""
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import (
    ROLE_MAX_LEVEL,
    can_access_level,
    has_permission,
    permissions_of,
    visible_levels,
)
from app.core.security import decode_token
from app.db.session import get_db
from app.models.enums import Permission, Role, SecrecyLevel
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)

ROLE_LABELS = {
    Role.SYSADMIN: "系统管理员",
    Role.RECORDS_MANAGER: "档案管理员",
    Role.VIEWER: "查阅者",
}


def _unauthorized(message: str = "未登录或登录已过期") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=message,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise _unauthorized()

    payload = decode_token(credentials.credentials)
    if not payload or payload.get("type") != "access":
        raise _unauthorized()

    try:
        user_id = int(payload.get("sub", "0"))
    except (TypeError, ValueError):
        raise _unauthorized() from None

    user = db.scalar(select(User).where(User.id == user_id, User.is_deleted.is_(False)))
    if user is None:
        raise _unauthorized("用户不存在")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用")
    # 改密或强制下线后 token_version 递增，旧 token 立即失效
    if int(payload.get("ver", 0)) != user.token_version:
        raise _unauthorized("登录状态已失效，请重新登录")
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被锁定")

    return user


def get_current_active_user(user: User = Depends(get_current_user)) -> User:
    if user.must_change_password:
        # 允许访问改密接口本身，其余接口由 need_password_change 拦截逻辑处理
        pass
    return user


def require_permission(*perms: Permission) -> Callable[..., User]:
    """要求同时具备全部指定权限点。"""

    def checker(user: User = Depends(get_current_user)) -> User:
        for p in perms:
            if not has_permission(user.role, p):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"缺少权限: {p.value}",
                )
        return user

    return checker


def require_role(*roles: Role) -> Callable[..., User]:
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in {r.value if isinstance(r, Role) else r for r in roles}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="角色无权执行此操作")
        return user

    return checker


def assert_level_access(user: User, level: SecrecyLevel | str) -> None:
    """单份资料的密级校验，不通过直接 403。"""
    if not can_access_level(user.role, level):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该资料密级超出您的访问范围",
        )


def level_filter_values(user: User) -> list[str]:
    """可用于 SQL IN 条件的可见密级值列表。"""
    return [lv.value for lv in visible_levels(user.role)]


def build_user_brief(user: User) -> dict:
    try:
        role = Role(user.role)
    except ValueError:
        role = Role.VIEWER
    max_rank = ROLE_MAX_LEVEL.get(role, 0)
    max_level = next((lv.value for lv in SecrecyLevel if lv.rank == max_rank), "internal")
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "role": role.value,
        "role_label": ROLE_LABELS.get(role, role.value),
        "department_name": user.department.name if user.department else None,
        "must_change_password": user.must_change_password,
        "permissions": permissions_of(role),
        "max_secrecy_level": max_level,
        "visible_levels": [lv.value for lv in visible_levels(role)],
    }


def get_request_ip(request: Request) -> str | None:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None
