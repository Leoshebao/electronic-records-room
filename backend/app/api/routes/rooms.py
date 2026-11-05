"""资料室与类目管理接口。

类目为三级树：一级（大类）→ 二级（中类）→ 三级（小类），
用 path 字段（如 "1/5/9"）支持前缀匹配做整棵子树查询。
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import build_user_brief, get_current_user, require_permission
from app.db.session import get_db
from app.models.document import Document
from app.models.enums import AuditAction, Permission
from app.models.room import Category, Room
from app.models.user import User
from app.services.audit import write_audit

router = APIRouter(prefix="/rooms", tags=["rooms"])
cat_router = APIRouter(prefix="/categories", tags=["categories"])

MAX_CATEGORY_DEPTH = 3


# ---------------- Schemas ----------------


class RoomCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9_-]+$")
    description: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=200)
    keeper_id: int | None = None
    sort_order: int = 0


class RoomUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=200)
    keeper_id: int | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class RoomOut(BaseModel):
    id: int
    name: str
    code: str
    description: str | None
    location: str | None
    keeper_id: int | None
    keeper_name: str | None = None
    is_active: bool
    sort_order: int
    doc_count: int = 0

    model_config = {"from_attributes": True}


class CategoryCreate(BaseModel):
    room_id: int
    name: str = Field(min_length=1, max_length=100)
    parent_id: int | None = None
    code: str | None = Field(default=None, max_length=32)
    sort_order: int = 0
    remark: str | None = Field(default=None, max_length=500)


class CategoryUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    code: str | None = Field(default=None, max_length=32)
    sort_order: int | None = None
    remark: str | None = Field(default=None, max_length=500)


# ---------------- 资料室 ----------------


@router.get("")
def list_rooms(
    include_inactive: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """列出资料室，附带各室当前用户可见的资料数量。"""
    from app.api.deps import level_filter_values

    stmt = select(Room).where(Room.is_deleted.is_(False))
    if not include_inactive:
        stmt = stmt.where(Room.is_active.is_(True))
    rooms = db.scalars(stmt.order_by(Room.sort_order, Room.id)).all()

    levels = level_filter_values(user)
    counts: dict[int, int] = {}
    if rooms:
        rows = db.execute(
            select(Document.room_id, func.count(Document.id))
            .where(
                Document.is_deleted.is_(False),
                Document.room_id.in_([r.id for r in rooms]),
                Document.secrecy_level.in_(levels),
            )
            .group_by(Document.room_id)
        ).all()
        counts = {rid: cnt for rid, cnt in rows}

    keeper_ids = {r.keeper_id for r in rooms if r.keeper_id}
    keepers: dict[int, str] = {}
    if keeper_ids:
        keepers = {
            u.id: u.full_name
            for u in db.scalars(select(User).where(User.id.in_(keeper_ids))).all()
        }

    return [
        {
            "id": r.id,
            "name": r.name,
            "code": r.code,
            "description": r.description,
            "location": r.location,
            "keeper_id": r.keeper_id,
            "keeper_name": keepers.get(r.keeper_id) if r.keeper_id else None,
            "is_active": r.is_active,
            "sort_order": r.sort_order,
            "doc_count": counts.get(r.id, 0),
        }
        for r in rooms
    ]


@router.post("", response_model=RoomOut, status_code=status.HTTP_201_CREATED)
def create_room(
    payload: RoomCreate,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.ROOM_MANAGE)),
) -> RoomOut:
    if db.scalar(select(Room).where(Room.code == payload.code, Room.is_deleted.is_(False))):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="资料室编码已存在")
    if payload.keeper_id and not db.get(User, payload.keeper_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="负责人不存在")

    room = Room(**payload.model_dump())
    db.add(room)
    db.commit()
    db.refresh(room)

    write_audit(
        action=AuditAction.ROOM_CREATE,
        user=operator,
        target_type="room",
        target_id=room.id,
        detail={"name": room.name, "code": room.code},
        request=request,
    )
    return RoomOut.model_validate(room)


@router.patch("/{room_id}", response_model=RoomOut)
def update_room(
    room_id: int,
    payload: RoomUpdate,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.ROOM_MANAGE)),
) -> RoomOut:
    room = db.get(Room, room_id)
    if room is None or room.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料室不存在")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(room, field, value)
    db.commit()
    db.refresh(room)

    write_audit(
        action=AuditAction.ROOM_UPDATE,
        user=operator,
        target_type="room",
        target_id=room.id,
        detail={"changed": list(payload.model_dump(exclude_unset=True).keys())},
        request=request,
    )
    return RoomOut.model_validate(room)


@router.delete("/{room_id}")
def delete_room(
    room_id: int,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.ROOM_MANAGE)),
) -> dict:
    room = db.get(Room, room_id)
    if room is None or room.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料室不存在")

    doc_count = (
        db.scalar(
            select(func.count(Document.id)).where(
                Document.room_id == room_id, Document.is_deleted.is_(False)
            )
        )
        or 0
    )
    if doc_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"该资料室下还有 {doc_count} 份资料，不能删除",
        )

    room.is_deleted = True
    db.commit()
    write_audit(
        action=AuditAction.ROOM_DELETE,
        user=operator,
        target_type="room",
        target_id=room_id,
        detail={"name": room.name},
        request=request,
    )
    return {"message": f"资料室 {room.name} 已删除"}


# ---------------- 类目 ----------------


def _build_tree(nodes: list[Category]) -> list[dict]:
    by_parent: dict[int | None, list[Category]] = {}
    for n in nodes:
        by_parent.setdefault(n.parent_id, []).append(n)

    def walk(parent_id: int | None) -> list[dict]:
        out = []
        for n in sorted(by_parent.get(parent_id, []), key=lambda x: (x.sort_order, x.id)):
            out.append(
                {
                    "id": n.id,
                    "room_id": n.room_id,
                    "parent_id": n.parent_id,
                    "name": n.name,
                    "code": n.code,
                    "level": n.level,
                    "path": n.path,
                    "remark": n.remark,
                    "sort_order": n.sort_order,
                    "children": walk(n.id),
                }
            )
        return out

    return walk(None)


@router.get("/{room_id}/categories")
def room_category_tree(
    room_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[dict]:
    if not db.get(Room, room_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料室不存在")
    nodes = db.scalars(
        select(Category).where(
            Category.room_id == room_id, Category.is_deleted.is_(False)
        )
    ).all()
    return _build_tree(list(nodes))


@cat_router.post("", status_code=status.HTTP_201_CREATED)
def create_category(
    payload: CategoryCreate,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.ROOM_MANAGE)),
) -> dict:
    if not db.get(Room, payload.room_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="资料室不存在")

    level = 1
    path_prefix = ""
    if payload.parent_id:
        parent = db.get(Category, payload.parent_id)
        if parent is None or parent.is_deleted:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上级类目不存在")
        if parent.room_id != payload.room_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上级类目不属于该资料室")
        level = parent.level + 1
        if level > MAX_CATEGORY_DEPTH:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"类目最多 {MAX_CATEGORY_DEPTH} 级",
            )
        path_prefix = parent.path

    dup = db.scalar(
        select(Category).where(
            Category.room_id == payload.room_id,
            Category.parent_id == payload.parent_id,
            Category.name == payload.name,
            Category.is_deleted.is_(False),
        )
    )
    if dup:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="同级下已存在同名类目")

    cat = Category(
        room_id=payload.room_id,
        parent_id=payload.parent_id,
        name=payload.name,
        code=payload.code,
        level=level,
        path="",
        remark=payload.remark,
        sort_order=payload.sort_order,
    )
    db.add(cat)
    db.flush()
    cat.path = f"{path_prefix}/{cat.id}" if path_prefix else str(cat.id)
    db.commit()
    db.refresh(cat)

    write_audit(
        action=AuditAction.CATEGORY_CREATE,
        user=operator,
        target_type="category",
        target_id=cat.id,
        detail={"name": cat.name, "level": level, "room_id": cat.room_id},
        request=request,
    )
    return {"id": cat.id, "name": cat.name, "level": cat.level, "path": cat.path}


@cat_router.patch("/{category_id}")
def update_category(
    category_id: int,
    payload: CategoryUpdate,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.ROOM_MANAGE)),
) -> dict:
    cat = db.get(Category, category_id)
    if cat is None or cat.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="类目不存在")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(cat, field, value)
    db.commit()
    db.refresh(cat)
    return {"id": cat.id, "name": cat.name, "level": cat.level, "path": cat.path}


@cat_router.delete("/{category_id}")
def delete_category(
    category_id: int,
    request: Request,
    db: Session = Depends(get_db),
    operator: User = Depends(require_permission(Permission.ROOM_MANAGE)),
) -> dict:
    cat = db.get(Category, category_id)
    if cat is None or cat.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="类目不存在")

    # 子树内只要挂有资料就不允许删除
    subtree_count = (
        db.scalar(
            select(func.count(Document.id)).where(
                Document.is_deleted.is_(False),
                Document.category_id.in_(
                    select(Category.id).where(
                        Category.path.like(f"{cat.path}%"), Category.is_deleted.is_(False)
                    )
                ),
            )
        )
        or 0
    )
    if subtree_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"该类目及其子类目下有 {subtree_count} 份资料，不能删除",
        )

    children = db.scalars(
        select(Category).where(Category.path.like(f"{cat.path}/%"), Category.is_deleted.is_(False))
    ).all()
    for c in children:
        c.is_deleted = True
    cat.is_deleted = True
    db.commit()

    write_audit(
        action=AuditAction.CATEGORY_DELETE,
        user=operator,
        target_type="category",
        target_id=category_id,
        detail={"deleted_with_children": len(children)},
        request=request,
    )
    return {"message": "类目已删除", "children_deleted": len(children)}


@cat_router.get("/tree")
def all_category_tree(
    room_id: int | None = Query(default=None, description="指定资料室时返回该类目树数组，否则返回按资料室分组的结构"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """类目树。

    - 传 room_id：返回该资料室的类目树数组（前端资料室/文档页使用）；
    - 不传：返回按资料室分组的全量结构，供左侧导航一次加载。
    """
    if room_id is not None:
        room = db.get(Room, room_id)
        if not room or room.is_deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="资料室不存在")
        nodes = db.scalars(
            select(Category)
            .where(Category.room_id == room_id, Category.is_deleted.is_(False))
            .order_by(Category.sort_order, Category.id)
        ).all()
        return _build_tree(list(nodes))

    rooms = db.scalars(
        select(Room).where(Room.is_deleted.is_(False), Room.is_active.is_(True)).order_by(Room.sort_order)
    ).all()
    nodes = db.scalars(select(Category).where(Category.is_deleted.is_(False))).all()
    by_room: dict[int, list[Category]] = {}
    for n in nodes:
        by_room.setdefault(n.room_id, []).append(n)

    return {
        "rooms": [
            {
                "id": r.id,
                "name": r.name,
                "code": r.code,
                "categories": _build_tree(by_room.get(r.id, [])),
            }
            for r in rooms
        ],
        "user": build_user_brief(user),
    }
