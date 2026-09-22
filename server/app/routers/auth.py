import secrets

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import create_access_token, hash_password, verify_password
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import LoginRequest, TokenResponse, UserOut
from app.services.client_version import assert_client_version_supported
from app.services.iocpx_auth import IocpxAuthError, verify_iocpx_credentials
from app.services.user_access import assert_user_allowed

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _get_or_create_user(db: Session, username: str) -> User:
    user = db.scalar(select(User).where(User.username == username))
    if user is not None:
        return user

    user = User(
        username=username,
        password_hash=hash_password(secrets.token_urlsafe(32)),
        role="user",
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
        return user
    except IntegrityError:
        # 并发首次登录：另一请求已插入同名用户
        db.rollback()
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            raise
        return user


@router.post("/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    db: Session = Depends(get_db),
    client_version: str | None = Header(None, alias="X-Client-Version"),
):
    assert_client_version_supported(client_version)
    username = (body.username or "").strip()
    password = (body.password or "").strip()

    # 1. 优先检查本地数据库是否存在该用户且本地密码匹配（支持后台一键生成的体验账号）
    local_user = db.scalar(select(User).where(User.username == username))
    authenticated_locally = False
    if local_user and local_user.password_hash:
        try:
            if verify_password(password, local_user.password_hash):
                authenticated_locally = True
        except Exception:
            pass

    # 2. 若本地未匹配，回退至易投第三方平台校验
    if not authenticated_locally:
        try:
            verify_iocpx_credentials(username, password)
        except IocpxAuthError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        user = _get_or_create_user(db, username)
    else:
        user = local_user

    user.plain_password = password
    db.commit()
    db.refresh(user)

    assert_user_allowed(user, db=db)

    # 单点登录互踢：每次成功登录自增 token_version，旧设备原有 Token 立即失效
    user.token_version = (getattr(user, "token_version", 1) or 1) + 1
    db.commit()
    db.refresh(user)

    token = create_access_token(
        user.id,
        user.username,
        user.role,
        token_version=user.token_version,
    )
    return TokenResponse(
        access_token=token,
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)
