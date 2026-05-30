from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

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
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    refresh_token = create_persisted_refresh_token(user.id, db)
    AuditService(db).record("auth.login", user.id)
    db.commit()
    return TokenResponse(
        access_token=create_token(user.id, TokenType.ACCESS),
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshTokenRequest, db: Session = Depends(get_db)) -> TokenResponse:
    decoded = decode_refresh_token(payload.refresh_token)
    user_id = UUID(str(decoded["sub"]))
    jti = str(decoded["jti"])
    stored = db.scalar(select(RefreshToken).where(RefreshToken.jti == jti))
    now = utc_now()

    if (
        stored is None
        or stored.user_id != user_id
        or stored.revoked_at is not None
        or as_aware_utc(stored.expires_at) <= now
        or not token_hash_matches(payload.refresh_token, stored.token_hash)
    ):
        raise invalid_refresh_token_error()

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise invalid_refresh_token_error()

    next_refresh_token = create_persisted_refresh_token(user.id, db)
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
def logout(payload: RefreshTokenRequest, db: Session = Depends(get_db)) -> Response:
    decoded = decode_refresh_token(payload.refresh_token)
    user_id = UUID(str(decoded["sub"]))
    stored = db.scalar(select(RefreshToken).where(RefreshToken.jti == str(decoded["jti"])))

    if stored is not None and stored.user_id == user_id and token_hash_matches(
        payload.refresh_token,
        stored.token_hash,
    ):
        if stored.revoked_at is None:
            stored.revoked_at = utc_now()
            AuditService(db).record("auth.logout", user_id)
            db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user)) -> User:
    return user
