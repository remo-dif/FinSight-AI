from datetime import UTC, datetime, timedelta
from enum import StrEnum
from hashlib import sha256
from hmac import compare_digest
from typing import Any
from uuid import UUID, uuid4

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.user import RefreshToken, User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_token(
    subject: UUID,
    token_type: TokenType,
    expires_delta: timedelta | None = None,
    jti: str | None = None,
) -> str:
    now = datetime.now(UTC)
    expiry = now + (expires_delta or timedelta(minutes=settings.access_token_minutes))
    secret = (
        settings.jwt_refresh_secret_key
        if token_type == TokenType.REFRESH
        else settings.jwt_secret_key
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type.value,
        "iat": int(now.timestamp()),
        "exp": int(expiry.timestamp()),
    }
    if jti is not None:
        payload["jti"] = jti
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


def hash_token(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


def token_hash_matches(token: str, stored_hash: str) -> bool:
    return compare_digest(hash_token(token), stored_hash)


def create_persisted_refresh_token(
    user_id: UUID,
    db: Session,
    expires_delta: timedelta = timedelta(days=30),
) -> str:
    jti = str(uuid4())
    token = create_token(user_id, TokenType.REFRESH, expires_delta, jti=jti)
    payload = jwt.decode(token, settings.jwt_refresh_secret_key, algorithms=[settings.jwt_algorithm])
    refresh_token = RefreshToken(
        user_id=user_id,
        jti=jti,
        token_hash=hash_token(token),
        expires_at=datetime.fromtimestamp(int(payload["exp"]), UTC),
    )
    db.add(refresh_token)
    return token


def decode_refresh_token(token: str) -> dict[str, Any]:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.jwt_refresh_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        if payload.get("type") != TokenType.REFRESH.value or not payload.get("jti"):
            raise credentials_error
        UUID(str(payload.get("sub")))
        return payload
    except (JWTError, ValueError):
        raise credentials_error from None


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != TokenType.ACCESS.value:
            raise credentials_error
        user_id = UUID(str(payload.get("sub")))
    except (JWTError, ValueError):
        raise credentials_error from None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise credentials_error
    return user


def require_role(*roles: UserRole):
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return user

    return dependency
