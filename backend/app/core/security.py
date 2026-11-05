"""密码哈希与 JWT 签发校验。"""
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# bcrypt 最多处理 72 字节，超长密码先截断避免静默失效
_BCRYPT_MAX_BYTES = 72


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain.encode("utf-8")[:_BCRYPT_MAX_BYTES].decode("utf-8", "ignore"))


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(
            plain.encode("utf-8")[:_BCRYPT_MAX_BYTES].decode("utf-8", "ignore"), hashed
        )
    except Exception:  # noqa: BLE001
        return False


def create_access_token(
    *,
    user_id: int,
    username: str,
    role: str,
    token_version: int = 1,
    must_change: bool = False,
    expires_minutes: int | None = None,
) -> tuple[str, int]:
    """签发 JWT。返回 (token, 有效期秒数)。"""
    minutes = expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "ver": token_version,
        "must_change": must_change,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "type": "access",
    }
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, minutes * 60


def decode_token(token: str) -> dict[str, Any] | None:
    """解码并校验签名/过期。失败返回 None，不抛异常给调用方。"""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.PyJWTError:
        return None


def generate_random_password(length: int = 12) -> str:
    """生成满足复杂度要求的随机初始密码。"""
    import secrets
    import string

    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pwd = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in pwd)
            and any(c.isupper() for c in pwd)
            and any(c.isdigit() for c in pwd)
        ):
            return pwd


def validate_password_strength(password: str) -> str | None:
    """返回错误信息；None 表示通过。"""
    if len(password) < 8:
        return "密码长度不得少于 8 位"
    if len(password) > 64:
        return "密码长度不得超过 64 位"
    if not any(c.isalpha() for c in password):
        return "密码必须包含字母"
    if not any(c.isdigit() for c in password):
        return "密码必须包含数字"
    return None
