import pytest
from fastapi import HTTPException
from starlette.responses import Response
from app.core.security import as_aware_utc, utc_now
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.routes.auth import login, logout, refresh, register
from app.core.database import Base
from app.core.security import hash_password
from app.models.user import RefreshToken, User
from app.schemas.auth import LoginRequest, RefreshTokenRequest, RegisterRequest, UserResponse


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def create_user(db: Session) -> User:
    user = User(
        email="user@example.com",
        full_name="Test User",
        password_hash=hash_password("correct horse battery staple"),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_register_response_schema_accepts_user_uuid(db: Session):
    user = register(
        RegisterRequest(
            email="new-user@example.com",
            password="correct horse battery staple",
            full_name="New User",
        ),
        db,
    )

    response = UserResponse.model_validate(user, from_attributes=True)

    assert response.id == user.id
    assert response.email == "new-user@example.com"
    assert response.full_name == "New User"
    assert response.role == "user"


def test_login_persists_hashed_refresh_token(db: Session):
    user = create_user(db)

    response = login(
        LoginRequest(email=user.email, password="correct horse battery staple"),
        Response(),
        db,
    )

    stored = db.scalar(select(RefreshToken).where(RefreshToken.user_id == user.id))
    assert response.token_type == "bearer"
    assert response.access_token
    assert response.refresh_token
    assert stored is not None
    assert stored.jti
    assert stored.token_hash != response.refresh_token
    assert len(stored.token_hash) == 64
    assert stored.revoked_at is None


def test_login_uses_configured_refresh_token_lifetime(db: Session, monkeypatch):
    monkeypatch.setattr("app.core.security.settings.refresh_token_days", 7)
    user = create_user(db)

    login(LoginRequest(email=user.email, password="correct horse battery staple"), Response(), db)

    stored = db.scalar(select(RefreshToken).where(RefreshToken.user_id == user.id))
    assert stored is not None
    remaining = as_aware_utc(stored.expires_at) - utc_now()
    assert 6 <= remaining.days <= 7


def test_refresh_rotates_and_revokes_previous_refresh_token(db: Session):
    user = create_user(db)
    login_response = login(
        LoginRequest(email=user.email, password="correct horse battery staple"),
        Response(),
        db,
    )
    original = db.scalar(select(RefreshToken).where(RefreshToken.user_id == user.id))

    rotated = refresh(RefreshTokenRequest(refresh_token=login_response.refresh_token), Response(), db)

    db.refresh(original)
    replacement = db.scalar(
        select(RefreshToken).where(RefreshToken.jti == original.replaced_by_jti),
    )
    assert rotated.access_token
    assert rotated.refresh_token != login_response.refresh_token
    assert original.revoked_at is not None
    assert replacement is not None
    assert replacement.revoked_at is None

    with pytest.raises(HTTPException) as exc:
        refresh(RefreshTokenRequest(refresh_token=login_response.refresh_token), Response(), db)
    assert exc.value.status_code == 401


def test_logout_revokes_refresh_token(db: Session):
    user = create_user(db)
    login_response = login(
        LoginRequest(email=user.email, password="correct horse battery staple"),
        Response(),
        db,
    )

    response = logout(RefreshTokenRequest(refresh_token=login_response.refresh_token), Response(), db)

    stored = db.scalar(select(RefreshToken).where(RefreshToken.user_id == user.id))
    assert response.status_code == 204
    assert stored.revoked_at is not None

    with pytest.raises(HTTPException) as exc:
        refresh(RefreshTokenRequest(refresh_token=login_response.refresh_token), Response(), db)
    assert exc.value.status_code == 401
