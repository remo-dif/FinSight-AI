from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    TokenType,
    as_aware_utc,
    create_persisted_refresh_token,
    create_token,
    decode_refresh_token,
    get_current_user,
    hash_password,
    token_hash_matches,
    utc_now,
    verify_password,
)
from app.models.user import RefreshToken, User
from app.schemas.auth import LoginRequest, RefreshTokenRequest, RegisterRequest, TokenResponse, UserResponse
from app.services.audit import AuditService

router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_COOKIE_NAME = "finsight_refresh_token"


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=60 * 60 * 24 * 30,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        path="/api/auth",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=REFRESH_COOKIE_NAME, path="/api/auth", samesite="lax")


def refresh_token_from_request(
    payload: RefreshTokenRequest,
    cookie_token: str | None,
) -> str:
    token = payload.refresh_token or cookie_token
    if not token:
        raise invalid_refresh_token_error()
    return token


def invalid_refresh_token_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> User:
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered")
    user = User(
        email=payload.email,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.flush()
    AuditService(db).record("auth.register", user.id)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    refresh_token = create_persisted_refresh_token(user.id, db)
    set_refresh_cookie(response, refresh_token)
    AuditService(db).record("auth.login", user.id)
    db.commit()
    return TokenResponse(
        access_token=create_token(user.id, TokenType.ACCESS),
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    payload: RefreshTokenRequest,
    response: Response,
    db: Session = Depends(get_db),
    cookie_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
) -> TokenResponse:
    refresh_token = refresh_token_from_request(payload, cookie_token)
    decoded = decode_refresh_token(refresh_token)
    user_id = UUID(str(decoded["sub"]))
    jti = str(decoded["jti"])
    stored = db.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
    now = utc_now()

    if (
        stored is None
        or stored.user_id != user_id
        or stored.revoked_at is not None
        or as_aware_utc(stored.expires_at) <= now
        or not token_hash_matches(refresh_token, stored.token_hash)
    ):
        raise invalid_refresh_token_error()

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise invalid_refresh_token_error()

    next_refresh_token = create_persisted_refresh_token(user.id, db)
    set_refresh_cookie(response, next_refresh_token)
    next_payload = decode_refresh_token(next_refresh_token)
    stored.revoked_at = now
    stored.replaced_by_jti = str(next_payload["jti"])
    AuditService(db).record("auth.refresh", user.id)
    db.commit()
    return TokenResponse(
        access_token=create_token(user.id, TokenType.ACCESS),
        refresh_token=next_refresh_token,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    payload: RefreshTokenRequest,
    response: Response,
    db: Session = Depends(get_db),
    cookie_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
) -> Response:
    refresh_token = refresh_token_from_request(payload, cookie_token)
    decoded = decode_refresh_token(refresh_token)
    user_id = UUID(str(decoded["sub"]))
    stored = db.scalar(select(RefreshToken).where(RefreshToken.jti == str(decoded["jti"])))

    if stored is not None and stored.user_id == user_id and token_hash_matches(refresh_token, stored.token_hash):
        if stored.revoked_at is None:
            stored.revoked_at = utc_now()
            AuditService(db).record("auth.logout", user_id)
            db.commit()
    clear_refresh_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> User:
    return user
