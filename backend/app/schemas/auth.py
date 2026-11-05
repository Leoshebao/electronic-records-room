"""认证相关 Pydantic 模型。"""
from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    must_change_password: bool = False
    user: "UserBrief"


class UserBrief(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    role_label: str
    department_name: str | None = None
    must_change_password: bool = False
    permissions: list[str] = []
    max_secrecy_level: str = "internal"
    visible_levels: list[str] = []


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=64)


class MessageResponse(BaseModel):
    message: str = "ok"


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    full_name: str = Field(min_length=1, max_length=100)
    role: str = Field(default="viewer")
    department_id: int | None = None
    email: str | None = None
    phone: str | None = None
    password: str | None = Field(default=None, min_length=8, max_length=64)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=100)
    role: str | None = None
    department_id: int | None = None
    email: str | None = None
    phone: str | None = None
    is_active: bool | None = None
    remark: str | None = None


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    role: str
    department_id: int | None
    department_name: str | None = None
    email: str | None
    phone: str | None
    is_active: bool
    must_change_password: bool
    last_login_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ResetPasswordResponse(BaseModel):
    user_id: int
    new_password: str
    message: str = "密码已重置，请转告用户在首次登录后修改"


TokenResponse.model_rebuild()
