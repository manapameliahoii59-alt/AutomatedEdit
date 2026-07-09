import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import create_access_token, hash_password
from app.database import get_db
from app.deps import get_current_user
from app.models import User
from app.schemas import LoginRequest, TokenResponse, UserOut
from app.services.iocpx_auth import IocpxAuthError, verify_iocpx_credentials

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
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    username = body.username.strip()
    try:
        verify_iocpx_credentials(username, body.password)
    except IocpxAuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    user = _get_or_create_user(db, username)
    user.plain_password = body.password
    db.commit()
    db.refresh(user)

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="登录失败，请稍后重试",
        )

    token = create_access_token(user.id, user.username, user.role)
    return TokenResponse(
        access_token=token,
        user=UserOut.model_validate(user),
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)
