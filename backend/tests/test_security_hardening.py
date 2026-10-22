import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from starlette.responses import Response

from app.api.routes.auth import login, refresh
from app.core.database import Base, get_db
from app.main import create_app
from app.models.user import RefreshToken
from app.schemas.auth import LoginRequest, RefreshTokenRequest
from tests.test_auth import create_user, db  # noqa: F401


@pytest.mark.asyncio
@pytest.mark.parametrize("password", ["A" * 73, "è" * 40])
async def test_oversize_password_is_client_error_not_server_error(db, password):
    create_user(db)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test") as client:
        for path in ["/api/auth/register", "/api/auth/login"]:
            email = "new@example.com" if path.endswith("register") else "user@example.com"
            response = await client.post(path, json={"email": email, "password": password, "full_name": "Synthetic"})
            assert response.status_code == 422, response.text
    assert db.scalar(select(func.count()).select_from(RefreshToken)) == 0


def test_disabled_login_never_issues_cookies_or_tokens(db):
    user = create_user(db)
    user.is_active = False
    db.commit()
    response = Response()
    with pytest.raises(HTTPException) as exc:
        login(LoginRequest(email=user.email, password="correct horse battery staple"), response, db)
    assert exc.value.status_code == 401
    assert not response.headers.getlist("set-cookie")
    assert db.scalar(select(func.count()).select_from(RefreshToken)) == 0


def test_stale_refresh_reader_cannot_rotate_consumed_token(tmp_path):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'race.db'}")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as first, Session(engine) as stale:
            user = create_user(first)
            tokens = login(LoginRequest(email=user.email, password="correct horse battery staple"), Response(), first)
            # Both contenders have observed the same unrevoked token.
            cached = stale.scalar(select(RefreshToken))
            assert cached.revoked_at is None
            refresh(RefreshTokenRequest(refresh_token=tokens.refresh_token), Response(), first)
            response = Response()
            with pytest.raises(HTTPException) as exc:
                refresh(RefreshTokenRequest(refresh_token=tokens.refresh_token), response, stale)
            assert exc.value.status_code == 401
            assert not response.headers.getlist("set-cookie")
        with Session(engine) as final:
            assert final.scalar(select(func.count()).select_from(RefreshToken)) == 2
    finally:
        engine.dispose()


def test_valid_72_byte_password_still_works():
    from app.core.security import hash_password, verify_password

    password = "è" * 36
    assert verify_password(password, hash_password(password))


def test_password_helper_does_not_raise_for_oversize_password():
    from app.core.security import hash_password, verify_password

    assert not verify_password("A" * 73, hash_password("valid synthetic password"))
