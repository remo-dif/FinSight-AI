from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
from jose import JWTError, jwt
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
from app.core.session_cookies import (
    cookie_name,
    raw_cookies,
    secure_cookies,
    session_binding,
    session_cookie_path,
    unique_cookie,
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
SESSION_COOKIE_NAME = "finsight_session"


def _cookie_name(kind: str, family_id: UUID) -> str:
    return cookie_name(f"finsight_{kind}_{family_id.hex}")


def _request_refresh(payload: RefreshTokenRequest, request: Request | None, legacy: str | None):
    binding = session_binding(request) if request is not None else None
    if payload.refresh_token:
        return payload.refresh_token, None
    if request is None:
        return refresh_token_from_request(payload, legacy), None
    binding = binding or ""
    try:
        family_id = UUID(hex=binding)
        if family_id.hex != binding:
            raise ValueError
    except ValueError:
        raise invalid_refresh_token_error() from None
    authorization = request.headers.get("authorization", "")
    if authorization:
        try:
            scheme, access_token = authorization.split(" ", 1)
            access = jwt.decode(
                access_token,
                settings.jwt_secret_key,
                algorithms=[settings.jwt_algorithm],
                options={"verify_exp": False},
            )
            if (
                scheme.lower() != "bearer"
                or access.get("type") != "access"
                or UUID(str(access.get("sid"))) != family_id
            ):
                raise ValueError
        except (ValueError, JWTError):
            raise invalid_refresh_token_error() from None
    token = unique_cookie(request, _cookie_name("refresh", family_id))
    if not token:
        raise invalid_refresh_token_error()
    return token, family_id


def set_access_cookie(response: Response, token: str, family_id: UUID | None = None) -> None:
    response.set_cookie(
        key=_cookie_name("access", family_id) if family_id else ACCESS_COOKIE_NAME,
        value=token,
        max_age=settings.access_token_minutes * 60,
        httponly=True,
        secure=secure_cookies(),
        samesite="lax",
        path="/",
    )


def clear_access_cookie(response: Response, family_id: UUID | None = None) -> None:
    response.delete_cookie(
        key=_cookie_name("access", family_id) if family_id else ACCESS_COOKIE_NAME,
        path="/",
        samesite="lax",
        httponly=True,
        secure=secure_cookies(),
    )


def set_refresh_cookie(response: Response, token: str, family_id: UUID | None = None) -> None:
    response.set_cookie(
        key=_cookie_name("refresh", family_id) if family_id else REFRESH_COOKIE_NAME,
        value=token,
        max_age=settings.refresh_token_days * 60 * 60 * 24,
        httponly=True,
        secure=secure_cookies(),
        samesite="lax",
        path=session_cookie_path() if family_id else "/api/auth",
    )


def clear_refresh_cookie(response: Response, family_id: UUID | None = None) -> None:
    response.delete_cookie(
        key=_cookie_name("refresh", family_id) if family_id else REFRESH_COOKIE_NAME,
        path=session_cookie_path() if family_id else "/api/auth",
        samesite="lax",
        httponly=True,
        secure=secure_cookies(),
    )


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
    cookie_session: Annotated[bool, Header(alias="X-FinSight-Cookie-Session")] = False,
    request: Request = None,
) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == payload.email))
    password_hash = (
        user.password_hash if user is not None and user.is_active else DUMMY_PASSWORD_HASH
    )
    password_valid = verify_password(payload.password, password_hash)
    if user is None or not user.is_active or not password_valid:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    try:
        family = RefreshTokenFamily(user_id=user.id)
        db.add(family)
        db.flush()
        refresh_token = create_persisted_refresh_token(user.id, db, family_id=family.id)
        AuditService(db).record("auth.login", user.id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    # Delete only slots observed in this request. Concurrent logins issue fresh UUIDs.
    if request is not None:
        observed = dict.fromkeys(name for name, _ in raw_cookies(request))
        remaining = 16
        for name in observed:
            if remaining == 0:
                break
            for kind in ("refresh", "access"):
                prefix = cookie_name(f"finsight_{kind}_")
                if name.startswith(prefix):
                    suffix = name[len(prefix) :]
                    try:
                        previous = UUID(hex=suffix)
                    except ValueError:
                        continue
                    if previous.hex == suffix and previous != family.id:
                        remaining -= 1
                        if kind == "refresh":
                            clear_refresh_cookie(response, previous)
                        else:
                            clear_access_cookie(response, previous)
    # Only login changes the selected family. Refresh/logout never write this selector.
    response.set_cookie(
        cookie_name(SESSION_COOKIE_NAME),
        family.id.hex,
        max_age=settings.refresh_token_days * 86400,
        httponly=True,
        secure=secure_cookies(),
        samesite="lax",
        path="/",
    )
    clear_refresh_cookie(response)  # Retire legacy cookie identity; never select it again.
    clear_access_cookie(response)
    set_refresh_cookie(response, refresh_token, family.id)
    access_token = create_token(user.id, TokenType.ACCESS, session_id=family.id)
    set_access_cookie(response, access_token, family.id)
    return TokenResponse(
        access_token=access_token,
        refresh_token="" if cookie_session else refresh_token,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh(
    payload: RefreshTokenRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    cookie_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    request: Request = None,
) -> TokenResponse:
    refresh_token, selected_family = _request_refresh(payload, request, cookie_token)
    decoded = decode_refresh_token(refresh_token)
    user_id = UUID(str(decoded["sub"]))
    jti = str(decoded["jti"])
    stored, family = _verified_refresh_family(refresh_token, user_id, jti, db)
    if selected_family is not None and family.id != selected_family:
        raise invalid_refresh_token_error()
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
    set_refresh_cookie(response, next_refresh_token, family.id)
    access_token = create_token(user.id, TokenType.ACCESS, session_id=family.id)
    set_access_cookie(response, access_token, family.id)
    return TokenResponse(
        access_token=access_token, refresh_token=next_refresh_token if payload.refresh_token else ""
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    payload: RefreshTokenRequest,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    cookie_token: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    request: Request = None,
) -> Response:
    refresh_token, selected_family = _request_refresh(payload, request, cookie_token)
    decoded = decode_refresh_token(refresh_token)
    user_id = UUID(str(decoded["sub"]))
    stored = db.scalar(select(RefreshToken).where(RefreshToken.jti == str(decoded["jti"])))
    if selected_family is not None and (stored is None or stored.family_id != selected_family):
        raise invalid_refresh_token_error()
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
    if stored is not None:
        clear_refresh_cookie(response, stored.family_id)
        clear_access_cookie(response, stored.family_id)
    # Keep the selector: deleting a fixed cookie could erase a later login.
    # A selected revoked family cannot refresh or authorize its bound access JWT.
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
