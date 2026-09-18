from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.auth import decode_access_token
from app.database import get_db
from app.models import User
from app.services.client_version import assert_client_version_supported
from app.services.user_access import assert_user_allowed

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
    client_version: str | None = Header(None, alias="X-Client-Version"),
) -> User:
    assert_client_version_supported(client_version)
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或令牌无效")
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
        user_id = int(payload.get("sub", 0))
    except (JWTError, ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或令牌无效") from None

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录或令牌无效")

    token_ver = payload.get("ver")
    expected_ver = getattr(user, "token_version", 1) or 1
    if token_ver is not None:
        if token_ver != expected_ver:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="您的账号已在另一台设备登录，当前会话已过期失效，请重新登录",
            )
    else:
        if expected_ver > 1:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="您的账号已在另一台设备登录，当前会话已过期失效，请重新登录",
            )

    assert_user_allowed(user)
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


def get_optional_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User | None:
    if credentials is None or not credentials.credentials:
        return None
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload.get("sub", 0))
        user = db.get(User, user_id)
        if user is not None and user.is_active:
            token_ver = payload.get("ver")
            expected_ver = getattr(user, "token_version", 1) or 1
            if token_ver is not None and token_ver != expected_ver:
                return None
            if token_ver is None and expected_ver > 1:
                return None
            return user
    except Exception:
        pass
    return None

