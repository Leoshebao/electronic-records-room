"""角色 → 权限点映射，以及密级可见性矩阵（设计文档核心约束）。

三条铁律：
1. 服务端逐请求校验，前端隐藏不构成安全边界；
2. 角色固定三类，不允许第 4 种角色出现；
3. 密级可见性由角色等级决定，管理员可见全部四级。
"""
from app.models.enums import Permission, Role, SecrecyLevel

# ---- 角色 → 功能权限 ----
ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.SYSADMIN: {
        Permission.DOC_VIEW,
        Permission.DOC_UPLOAD,
        Permission.DOC_EDIT,
        Permission.DOC_DELETE,
        Permission.DOC_DOWNLOAD,
        Permission.DOC_PRINT,
        Permission.BORROW_APPLY,
        Permission.BORROW_APPROVE,
        Permission.ROOM_MANAGE,
        Permission.USER_MANAGE,
        Permission.AUDIT_VIEW,
        Permission.SYSTEM_CONFIG,
        Permission.BACKUP_MANAGE,
        Permission.SECRET_ACCESS,
    },
    Role.RECORDS_MANAGER: {
        Permission.DOC_VIEW,
        Permission.DOC_UPLOAD,
        Permission.DOC_EDIT,
        Permission.DOC_DELETE,
        Permission.DOC_DOWNLOAD,
        Permission.DOC_PRINT,
        Permission.BORROW_APPLY,
        Permission.BORROW_APPROVE,
        Permission.ROOM_MANAGE,
        Permission.AUDIT_VIEW,
        Permission.SECRET_ACCESS,
    },
    Role.VIEWER: {
        Permission.DOC_VIEW,
        Permission.BORROW_APPLY,
    },
}

# ---- 角色 → 可访问的最高密级（3×4 矩阵的等价表述）----
# sysadmin    : 公开/内部/秘密/机密  全可见
# manager     : 公开/内部/秘密        机密不可见
# viewer      : 公开/内部             秘密与机密均不可见
ROLE_MAX_LEVEL: dict[Role, int] = {
    Role.SYSADMIN: SecrecyLevel.CONFIDENTIAL.rank,
    Role.RECORDS_MANAGER: SecrecyLevel.SECRET.rank,
    Role.VIEWER: SecrecyLevel.INTERNAL.rank,
}

LEVEL_LABELS = {
    SecrecyLevel.PUBLIC: "公开",
    SecrecyLevel.INTERNAL: "内部",
    SecrecyLevel.SECRET: "秘密",
    SecrecyLevel.CONFIDENTIAL: "机密",
}


def has_permission(role: Role | str, permission: Permission | str) -> bool:
    """判断角色是否拥有某功能权限。"""
    try:
        r = Role(role) if isinstance(role, str) else role
        p = Permission(permission) if isinstance(permission, str) else permission
    except ValueError:
        return False
    return p in ROLE_PERMISSIONS.get(r, set())


def can_access_level(role: Role | str, level: SecrecyLevel | str) -> bool:
    """判断角色能否看到指定密级的资料。"""
    try:
        r = Role(role) if isinstance(role, str) else role
        lv = SecrecyLevel(level) if isinstance(level, str) else level
    except ValueError:
        return False
    return lv.rank <= ROLE_MAX_LEVEL.get(r, -1)


def visible_levels(role: Role | str) -> list[SecrecyLevel]:
    """返回该角色可见的密级列表，用于 SQL 过滤条件。"""
    try:
        r = Role(role) if isinstance(role, str) else role
    except ValueError:
        return []
    limit = ROLE_MAX_LEVEL.get(r, -1)
    return [lv for lv in SecrecyLevel if lv.rank <= limit]


def permissions_of(role: Role | str) -> list[str]:
    try:
        r = Role(role) if isinstance(role, str) else role
    except ValueError:
        return []
    return sorted(p.value for p in ROLE_PERMISSIONS.get(r, set()))
