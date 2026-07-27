from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.errors import ApiCodes, BusinessError
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)
DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise BusinessError(ApiCodes.UNAUTHORIZED, "请先登录", 401)

    payload = decode_access_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise BusinessError(ApiCodes.UNAUTHORIZED, "无效的登录凭证", 401)

    user = db.get(User, int(user_id))
    if user is None:
        raise BusinessError(ApiCodes.UNAUTHORIZED, "用户不存在", 401)
    if user.status != "active":
        raise BusinessError(ApiCodes.FORBIDDEN, "账号已被禁用，请联系管理员", 403)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: str):
    def dependency(current_user: CurrentUser) -> User:
        if current_user.role not in roles:
            raise BusinessError(ApiCodes.FORBIDDEN, "无权限访问", 403)
        return current_user

    return dependency


AdminUser = Annotated[User, Depends(require_roles("admin", "super_admin"))]
QcUser = Annotated[User, Depends(require_roles("qc"))]

