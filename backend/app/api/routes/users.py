"""用户与部门管理（仅系统管理员）。"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.api.deps import require_permission
from app.core.security import (
    generate_random_password,
    hash_password,
    validate_password_strength,
)
from app.db.session import get_db
from app.models.enums import AuditAction, Permission, Role
from app.models.user import Department, User
from app.schemas.auth import (
    MessageResponse,
    ResetPasswordResponse,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services.audit import write_audit

router = APIRouter(tags=["users"])

VALID_ROLES = {r.value for r in Role}


def _check_role(role: str) -> str:
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"角色必须是 {'/'.join(sorted(VALID_ROLES))} 之一",
        )
    return role


@router.get("/users")
def list_users(
    keyword: str | None = None,
    role: str | None = None,
    department_id: int | None = None,
    is_active: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.USER_MANAGE)),
) -> dict:
    stmt = select(User).where(User.is_deleted.is_(False)).options(joinedload(User.department))
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(User.username.ilike(like), User.full_name.ilike(like)))
    if role:
        stmt = stmt.where(User.role == role)
    if department_id:
        stmt = stmt.where(User.department_id == department_id)
    if is_active is not None:
        stmt = stmt.where(User.is_active.is_(is_active))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [UserOut.model_validate(u).model_dump() for u in rows],
    }


@router.post("/users", response_model=dict, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.USER_MANAGE)),
) -> dict:
    _check_role(payload.role)

    if db.scalar(select(User).where(User.username == payload.username)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="登录名已存在")

    if payload.department_id and not db.get(Department, payload.department_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="部门不存在")

    plain = payload.password or generate_random_password()
    if payload.password:
        err = validate_password_strength(payload.password)
        if err:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)

    user = User(
        username=payload.username,
        full_name=payload.full_name,
        role=payload.role,
        department_id=payload.department_id,
        email=payload.email,
        phone=payload.phone,
        password_hash=hash_password(plain),
        is_active=True,
        must_change_password=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    write_audit(
        action=AuditAction.USER_CREATE,
        user=operator,
        target_type="user",
        target_id=user.id,
        detail={"username": user.username, "role": user.role},
        request=request,
    )

    result = UserOut.model_validate(user).model_dump()
    # 仅在未显式指定密码时回显随机密码，方便管理员转告
    if not payload.password:
        result["initial_password"] = plain
    return result


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.USER_MANAGE)),
) -> UserOut:
    user = db.get(User, user_id)
    if user is None or user.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    # 不允许管理员把自己降级或停用，避免锁死系统
    if user.id == operator.id:
        if payload.role is not None and payload.role != operator.role:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能修改自己的角色")
        if payload.is_active is False:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能停用自己")

    changed: dict = {}
    if payload.role is not None:
        _check_role(payload.role)
        if payload.role != user.role:
            changed["role"] = f"{user.role}->{payload.role}"
            user.role = payload.role
            user.token_version += 1  # 角色变更立即生效
    if payload.full_name is not None:
        user.full_name = payload.full_name
        changed["full_name"] = payload.full_name
    if payload.department_id is not None:
        if payload.department_id and not db.get(Department, payload.department_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="部门不存在")
        user.department_id = payload.department_id or None
        changed["department_id"] = payload.department_id
    if payload.email is not None:
        user.email = payload.email
    if payload.phone is not None:
        user.phone = payload.phone
    if payload.remark is not None:
        user.remark = payload.remark
    if payload.is_active is not None and payload.is_active != user.is_active:
        user.is_active = payload.is_active
        changed["is_active"] = payload.is_active
        if not payload.is_active:
            user.token_version += 1

    db.commit()
    db.refresh(user)

    write_audit(
        action=AuditAction.USER_UPDATE,
        user=operator,
        target_type="user",
        target_id=user.id,
        detail={"changed": changed},
        request=request,
    )
    return UserOut.model_validate(user)


@router.post("/users/{user_id}/reset-password", response_model=ResetPasswordResponse)
def reset_password(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.USER_MANAGE)),
) -> ResetPasswordResponse:
    user = db.get(User, user_id)
    if user is None or user.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    plain = generate_random_password()
    user.password_hash = hash_password(plain)
    user.must_change_password = True
    user.token_version += 1
    user.failed_login_count = 0
    user.locked_until = None
    db.commit()

    write_audit(
        action=AuditAction.USER_UPDATE,
        user=operator,
        target_type="user",
        target_id=user.id,
        detail={"field": "password", "reset_by_admin": True},
        request=request,
    )
    return ResetPasswordResponse(user_id=user.id, new_password=plain)


@router.delete("/users/{user_id}", response_model=MessageResponse)
def disable_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.USER_MANAGE)),
) -> MessageResponse:
    """停用账号（不物理删除，保留审计链路）。"""
    user = db.get(User, user_id)
    if user is None or user.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if user.id == operator.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能停用自己")

    user.is_active = False
    user.token_version += 1
    db.commit()

    write_audit(
        action=AuditAction.USER_DISABLE,
        user=operator,
        target_type="user",
        target_id=user.id,
        detail={"username": user.username},
        request=request,
    )
    return MessageResponse(message=f"用户 {user.username} 已停用")


# ---------------- 部门 ----------------

dept_router = APIRouter(prefix="/departments", tags=["departments"])


@dept_router.get("")
def list_departments(
    db: Session = Depends(get_db),
    _: User = Depends(require_permission(Permission.DOC_VIEW)),
) -> list[dict]:
    rows = db.scalars(
        select(Department).where(Department.is_deleted.is_(False)).order_by(Department.sort_order, Department.id)
    ).all()
    return [
        {
            "id": d.id,
            "name": d.name,
            "code": d.code,
            "parent_id": d.parent_id,
            "sort_order": d.sort_order,
            "is_active": d.is_active,
        }
        for d in rows
    ]


@dept_router.post("", status_code=status.HTTP_201_CREATED)
def create_department(
    name: str,
    code: str | None = None,
    parent_id: int | None = None,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.USER_MANAGE)),
) -> dict:
    if db.scalar(select(Department).where(Department.name == name, Department.is_deleted.is_(False))):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="部门名称已存在")
    dept = Department(name=name, code=code, parent_id=parent_id)
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return {"id": dept.id, "name": dept.name, "code": dept.code}
