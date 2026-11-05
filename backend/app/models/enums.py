"""业务枚举：角色、密级、状态。全部使用字符串枚举，落库为 varchar，便于扩展。"""
from enum import Enum


class Role(str, Enum):
    """三类角色，初次设计固定不可扩展。"""

    SYSADMIN = "sysadmin"            # 系统管理员：全权
    RECORDS_MANAGER = "records_manager"  # 档案管理员：业务全权，不含系统配置
    VIEWER = "viewer"                # 查阅者：仅按授权借阅查看


class SecrecyLevel(str, Enum):
    """四级密级，等级越高可见范围越小。"""

    PUBLIC = "public"            # 公开
    INTERNAL = "internal"        # 内部
    SECRET = "secret"            # 秘密
    CONFIDENTIAL = "confidential"  # 机密

    @property
    def rank(self) -> int:
        return {"public": 0, "internal": 1, "secret": 2, "confidential": 3}[self.value]

    @property
    def label(self) -> str:
        return {
            "public": "公开",
            "internal": "内部",
            "secret": "秘密",
            "confidential": "机密",
        }[self.value]


class DocStatus(str, Enum):
    DRAFT = "draft"              # 草稿（未发布）
    ACTIVE = "active"            # 在库
    ARCHIVED = "archived"        # 已归档（软删除）
    DESTROYED = "destroyed"      # 已销毁


class FileStatus(str, Enum):
    PENDING = "pending"          # 已登记待落盘
    STORED = "stored"            # 已落盘
    MISSING = "missing"          # 物理文件缺失
    DELETED = "deleted"          # 已删除


class OCRStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    SKIPPED = "skipped"


class BorrowStatus(str, Enum):
    PENDING = "pending"          # 待审批
    APPROVED = "approved"        # 已批准，借阅中
    REJECTED = "rejected"        # 已拒绝
    RETURNED = "returned"        # 已归还
    EXPIRED = "expired"          # 到期自动失效
    CANCELLED = "cancelled"      # 申请人撤回


class AuditAction(str, Enum):
    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    ROOM_CREATE = "room_create"
    ROOM_UPDATE = "room_update"
    ROOM_DELETE = "room_delete"
    CATEGORY_CREATE = "category_create"
    CATEGORY_UPDATE = "category_update"
    CATEGORY_DELETE = "category_delete"
    DOC_CREATE = "doc_create"
    DOC_UPDATE = "doc_update"
    DOC_DELETE = "doc_delete"
    DOC_VIEW = "doc_view"
    DOC_DOWNLOAD = "doc_download"
    DOC_PRINT = "doc_print"
    DOC_SEARCH = "doc_search"
    OCR_PROCESS = "ocr_process"
    BORROW_APPLY = "borrow_apply"
    BORROW_APPROVE = "borrow_approve"
    BORROW_REJECT = "borrow_reject"
    BORROW_RETURN = "borrow_return"
    BORROW_RENEW = "borrow_renew"
    BORROW_EXPIRE = "borrow_expire"
    USER_CREATE = "user_create"
    USER_UPDATE = "user_update"
    USER_DISABLE = "user_disable"
    PERM_CHANGE = "perm_change"
    CONFIG_CHANGE = "config_change"
    BACKUP = "backup"
    RESTORE = "restore"


class Permission(str, Enum):
    """功能级权限点。角色与权限的映射在 core/permissions.py 中定义。"""

    DOC_VIEW = "doc:view"
    DOC_UPLOAD = "doc:upload"
    DOC_EDIT = "doc:edit"
    DOC_DELETE = "doc:delete"
    DOC_DOWNLOAD = "doc:download"
    DOC_PRINT = "doc:print"
    BORROW_APPLY = "borrow:apply"
    BORROW_APPROVE = "borrow:approve"
    ROOM_MANAGE = "room:manage"
    USER_MANAGE = "user:manage"
    AUDIT_VIEW = "audit:view"
    SYSTEM_CONFIG = "system:config"
    BACKUP_MANAGE = "backup:manage"
    SECRET_ACCESS = "level:confidential"  # 可访问机密级
