from datetime import datetime, timedelta, timezone
from hashlib import md5
from typing import Any

import jwt

from app.core.errors import ApiCodes, BusinessError
from app.core.config import settings


def hash_password(password: str) -> str:
    return md5(password.encode("utf-8"), usedforsecurity=False).hexdigest().upper()


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    return hash_password(password).lower() == password_hash.strip().lower()


def create_access_token(user_id: int, username: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise BusinessError(ApiCodes.UNAUTHORIZED, "登录已过期", 401) from exc
    except jwt.InvalidTokenError as exc:
        raise BusinessError(ApiCodes.UNAUTHORIZED, "无效的登录凭证", 401) from exc

