"""初始化基础数据（幂等）：部门 + 管理员账号 +（可选）示例资料室与类目树。

启动脚本每次都会调用，已存在的记录自动跳过。
带 --with-samples 时额外创建首个资料室和三级示例类目，让新库开箱即可上传；
不带参数时只建部门与管理员，资料室由管理员在界面自行规划。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from passlib.context import CryptContext  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.models import Category, Department, Role, Room, User  # noqa: E402

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# (名称, 编码, 排序) —— 按公司实际组织架构增删
BASE_DEPARTMENTS = [
    ("综合部", "ZH", 10),
    ("技术部", "JS", 20),
    ("工程部", "GC", 30),
    ("财务部", "CW", 40),
]

# 示例资料室：(名称, 编码, 存放位置, 排序)
BASE_ROOM = ("综合档案室", "ZH", "办公楼档案室", 10)

# 示例三级类目：(编码, 名称, 排序, [(二级编码, 二级名称, 排序, [(三级编码, 三级名称, 排序)])])
BASE_CATEGORIES = [
    ("01", "行政管理", 10, [
        ("01.01", "会议纪要", 10, [("01.01.01", "年度工作会议", 10)]),
        ("01.02", "规章制度", 20, []),
    ]),
    ("02", "人事管理", 20, [
        ("02.01", "员工档案", 10, []),
    ]),
    ("03", "财务档案", 30, []),
]


def seed_departments(db) -> int:
    created = 0
    for name, code, sort_order in BASE_DEPARTMENTS:
        if db.scalar(select(Department).where(Department.code == code)):
            continue
        db.add(Department(name=name, code=code, sort_order=sort_order))
        created += 1
    if created:
        db.commit()
    return created


def seed_admin(db) -> bool:
    existing = db.scalar(select(User).where(User.username == settings.SEED_ADMIN_USERNAME))
    if existing:
        return False

    dept = db.scalar(select(Department).where(Department.code == "ZH"))
    admin = User(
        username=settings.SEED_ADMIN_USERNAME,
        full_name="系统管理员",
        password_hash=pwd_context.hash(settings.SEED_ADMIN_PASSWORD),
        role=Role.SYSADMIN,
        department_id=dept.id if dept else None,
        is_active=True,
        must_change_password=True,
    )
    db.add(admin)
    db.commit()
    return True


def seed_samples(db) -> tuple[str, int]:
    """创建示例资料室与三级类目树（幂等：按 room.code / 同级 name 判重）。"""
    name, code, location, sort_order = BASE_ROOM
    room = db.scalar(select(Room).where(Room.code == code))
    room_created = ""
    if room is None:
        room = Room(name=name, code=code, location=location, sort_order=sort_order, is_active=True)
        db.add(room)
        db.commit()
        db.refresh(room)
        room_created = room.name

    created = 0

    def add_children(parent: Category | None, items: list, level: int, parent_path: str) -> None:
        nonlocal created
        for item in items:
            c_code, c_name, c_sort = item[0], item[1], item[2]
            exists = db.scalar(
                select(Category).where(
                    Category.room_id == room.id,
                    Category.parent_id.is_(None) if parent is None else Category.parent_id == parent.id,
                    Category.name == c_name,
                )
            )
            if exists:
                node = exists
            else:
                node = Category(
                    room_id=room.id,
                    parent_id=parent.id if parent else None,
                    name=c_name,
                    code=c_code,
                    level=level,
                    path=parent_path,
                    sort_order=c_sort,
                    is_active=True,
                )
                db.add(node)
                db.commit()
                db.refresh(node)
                node.path = f"{parent_path}{node.id}/"
                db.commit()
                created += 1
            children = item[3] if len(item) > 3 else []
            if children and level < 3:
                add_children(node, children, level + 1, node.path)

    add_children(None, BASE_CATEGORIES, 1, "/")
    return room_created, created


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化基础数据")
    parser.add_argument(
        "--with-samples",
        action="store_true",
        help="同时创建示例资料室与三级类目树（建议仅在全新库首次部署时使用）",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        dept_count = seed_departments(db)
        total_dept = len(db.scalars(select(Department)).all())
        print(f"部门：新建 {dept_count} 个，当前共 {total_dept} 个")

        created = seed_admin(db)
        if created:
            print(f"已创建管理员: {settings.SEED_ADMIN_USERNAME}")
            print("首次登录后系统会强制要求修改默认密码")
        else:
            print(f"管理员 {settings.SEED_ADMIN_USERNAME} 已存在，跳过")

        if args.with_samples:
            room_name, cat_count = seed_samples(db)
            room_total = db.scalar(select(func.count(Room.id))) or 0
            cat_total = db.scalar(select(func.count(Category.id))) or 0
            print(f"示例资料室：{'新建 ' + room_name if room_name else '已存在，跳过'}")
            print(f"示例类目：新建 {cat_count} 个，当前全库共 {room_total} 个资料室 / {cat_total} 个类目")
        return 0
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        print(f"初始化失败: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
