from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.login_throttle import enforce_login_account_limit
from app.core.security import (
    DUMMY_PASSWORD_HASH,
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
from app.models.user import RefreshToken, RefreshTokenFamily, User
from app.schemas.auth import (
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    RegistrationResponse,
    TokenResponse,
    UserResponse,
)
from app.services.audit import AuditService

router = APIRouter(prefix="/auth", tags=["auth"])
REFRESH_COOKIE_NAME = "finsight_refresh_token"
ACCESS_COOKIE_NAME = "finsight_access_token"


def set_access_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=token,
        max_age=settings.access_token_minutes * 60,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        path="/",
    )


def clear_access_cookie(response: Response) -> None:
    response.delete_cookie(
        key=ACCESS_COOKIE_NAME,
        path="/",
        samesite="lax",
        secure=settings.app_env == "production",
    )


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=settings.refresh_token_days * 60 * 60 * 24,
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


@router.post("/register", response_model=RegistrationResponse, status_code=status.HTTP_202_ACCEPTED)
def register(
    payload: RegisterRequest, db: Annotated[Session, Depends(get_db)]
) -> RegistrationResponse:
    # Both paths perform the same configured expensive hashing operation.
    password_hash = hash_password(payload.password)
    existing = db.scalar(select(User).where(User.email == payload.email))
    if existing is not None:
        return RegistrationResponse()
    user = User(email=payload.email, full_name=payload.full_name, password_hash=password_hash)
    try:
        db.add(user)
        db.flush()
        AuditService(db).record("auth.register", user.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        # A concurrent registration may have won the email uniqueness race.
        if db.scalar(select(User.id).where(User.email == payload.email)) is None:
            raise
    except Exception:
        db.rollback()
        raise
    return RegistrationResponse()


@router.post(
    "/login", response_model=TokenResponse, dependencies=[Depends(enforce_login_account_limit)]
)
def login(
    payload: LoginRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email))
    password_hash = (
        user.password_hash if user is not None and user.is_active else DUMMY_PASSWORD_HASH
    )
    password_valid = verify_password(payload.password, password_hash)
    if user is None or not user.is_active or not password_valid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    try:
        refresh_token = create_persisted_refresh_token(user.id, db)
        AuditService(db).record("auth.login", user.id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    set_refresh_cookie(response, refresh_token)
    access_token = create_token(user.id, TokenType.ACCESS)
    set_access_cookie(response, access_token)
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    payload: RefreshTokenRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    cookie_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
) -> TokenResponse:
    refresh_token = refresh_token_from_request(payload, cookie_token)
    decoded = decode_refresh_token(refresh_token)
    user_id = UUID(str(decoded["sub"]))
    jti = str(decoded["jti"])
    stored, family = _verified_refresh_family(refresh_token, user_id, jti, db)
    now = utc_now()
    if family.revoked_at is not None:
        raise invalid_refresh_token_error()
    if stored.revoked_at is not None:
        try:
            _revoke_refresh_family(family, db, "auth.refresh_reuse")
            db.commit()
        except Exception:
            db.rollback()
            raise
        raise invalid_refresh_token_error()
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise invalid_refresh_token_error()

    try:
        consumed = db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.id == stored.id,
                RefreshToken.revoked_at.is_(None),
                RefreshToken.expires_at > now,
            )
            .values(revoked_at=now)
            .execution_options(synchronize_session=False)
        )
        if consumed.rowcount != 1:
            raise invalid_refresh_token_error()
        next_refresh_token = create_persisted_refresh_token(user.id, db, family_id=family.id)
        next_payload = decode_refresh_token(next_refresh_token)
        stored.revoked_at = now
        stored.replaced_by_jti = str(next_payload["jti"])
        AuditService(db).record("auth.refresh", user.id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    set_refresh_cookie(response, next_refresh_token)
    access_token = create_token(user.id, TokenType.ACCESS)
    set_access_cookie(response, access_token)
    return TokenResponse(access_token=access_token, refresh_token=next_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    payload: RefreshTokenRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    cookie_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
) -> Response:
    refresh_token = refresh_token_from_request(payload, cookie_token)
    decoded = decode_refresh_token(refresh_token)
    user_id = UUID(str(decoded["sub"]))
    stored = db.scalar(select(RefreshToken).where(RefreshToken.jti == str(decoded["jti"])))
    if (
        stored is not None
        and stored.user_id == user_id
        and token_hash_matches(refresh_token, stored.token_hash)
    ):
        family = db.scalar(
            select(RefreshTokenFamily)
            .where(RefreshTokenFamily.id == stored.family_id, RefreshTokenFamily.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if family is not None and family.revoked_at is None:
            try:
                _revoke_refresh_family(family, db, "auth.logout")
                db.commit()
            except Exception:
                db.rollback()
                raise
    clear_refresh_cookie(response)
    clear_access_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=UserResponse)
def me(user: Annotated[User, Depends(get_current_user)]) -> User:
    return user


def _verified_refresh_family(
    token: str, user_id: UUID, jti: str, db: Session
) -> tuple[RefreshToken, RefreshTokenFamily]:
    stored = db.scalar(
        select(RefreshToken)
        .where(RefreshToken.jti == jti)
        .execution_options(populate_existing=True)
    )
    if (
        stored is None
        or stored.user_id != user_id
        or not token_hash_matches(token, stored.token_hash)
    ):
        raise invalid_refresh_token_error()
    family = db.scalar(
        select(RefreshTokenFamily)
        .where(RefreshTokenFamily.id == stored.family_id, RefreshTokenFamily.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if family is None:
        raise invalid_refresh_token_error()
    # Re-read after acquiring the family lock: the first read may precede a rotation.
    db.refresh(stored)
    if as_aware_utc(stored.expires_at) <= utc_now():
        raise invalid_refresh_token_error()
    return stored, family


def _revoke_refresh_family(family: RefreshTokenFamily, db: Session, action: str) -> None:
    now = utc_now()
    family.revoked_at = now
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
        .execution_options(synchronize_session=False)
    )
    AuditService(db).record(action, family.user_id, {"family_id": str(family.id)})
