"""Security contracts: generic registration and refresh-family isolation."""

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.responses import Response

from app.api.routes import auth
from app.core.database import get_db
from app.main import create_app
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshTokenRequest
from tests import test_auth as auth_fixtures
from tests.test_auth import create_user

db = auth_fixtures.db
PASSWORD = "correct horse battery staple"


def sign_in(db, email="user@example.com"):
    return auth.login(LoginRequest(email=email, password=PASSWORD), Response(), db)


def rotate(db, token):
    return auth.refresh(RefreshTokenRequest(refresh_token=token), Response(), db)


@pytest.mark.asyncio
async def test_registration_has_same_public_contract_for_existing_and_new_accounts(db, monkeypatch):
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    payload = {"email": "privacy@example.com", "password": PASSWORD, "full_name": "Original Name"}
    hashing = auth.hash_password
    hash_calls = []

    def track_hash(password):
        hash_calls.append(True)
        return hashing(password)

    monkeypatch.setattr(auth, "hash_password", track_hash)
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = await client.post("/api/auth/register", json=payload)
            second = await client.post(
                "/api/auth/register",
                json={**payload, "password": "different-password", "full_name": "Replacement"},
            )
        assert first.status_code == second.status_code == 202
        assert len(hash_calls) == 2
        assert first.json() == second.json()
        assert set(first.json()) == {"message"}
        assert "set-cookie" not in first.headers and "set-cookie" not in second.headers
        user = db.scalar(select(User).where(User.email == payload["email"]))
        assert user.full_name == "Original Name"
        assert auth.verify_password(PASSWORD, user.password_hash)
    finally:
        app.dependency_overrides.clear()


def test_replayed_parent_revokes_descendants_but_not_independent_sessions(db):
    create_user(db)
    first = sign_in(db)
    independent = sign_in(db)
    child = rotate(db, first.refresh_token)
    with pytest.raises(HTTPException) as exc:
        rotate(db, first.refresh_token)
    assert exc.value.status_code == 401
    with pytest.raises(HTTPException) as exc:
        rotate(db, child.refresh_token)
    assert exc.value.status_code == 401
    assert rotate(db, independent.refresh_token).refresh_token


def test_logout_with_consumed_parent_revokes_current_descendant(db):
    create_user(db)
    first = sign_in(db)
    child = rotate(db, first.refresh_token)
    response = auth.logout(RefreshTokenRequest(refresh_token=first.refresh_token), Response(), db)
    assert response.status_code == 204
    with pytest.raises(HTTPException) as exc:
        rotate(db, child.refresh_token)
    assert exc.value.status_code == 401


@pytest.mark.parametrize("operation", ["rotation", "replay", "logout"])
def test_audit_failure_rolls_back_rotation_or_family_revocation(db, monkeypatch, operation):
    from app.models.user import RefreshToken, RefreshTokenFamily

    create_user(db)
    initial = sign_in(db)
    if operation in {"replay", "logout"}:
        rotate(db, initial.refresh_token)
    before = [
        (row.jti, row.revoked_at, row.replaced_by_jti)
        for row in db.scalars(select(RefreshToken).order_by(RefreshToken.jti))
    ]

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(auth.AuditService, "record", fail)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        if operation == "logout":
            auth.logout(RefreshTokenRequest(refresh_token=initial.refresh_token), Response(), db)
        else:
            rotate(db, initial.refresh_token)
    db.expire_all()
    after = [
        (row.jti, row.revoked_at, row.replaced_by_jti)
        for row in db.scalars(select(RefreshToken).order_by(RefreshToken.jti))
    ]
    assert before == after
    assert all(family.revoked_at is None for family in db.scalars(select(RefreshTokenFamily)))
    assert not db.dirty and not db.new


@pytest.mark.asyncio
async def test_account_throttle_runs_before_password_verification(db, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "login_account_rate_limit_per_minute", 2)
    monkeypatch.setattr(settings, "rate_limit_backend", "memory")
    calls = []
    monkeypatch.setattr(auth, "verify_password", lambda *args: calls.append(True) or False)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            replies = [
                await client.post(
                    "/api/auth/login", json={"email": "absent@example.com", "password": "wrong"}
                )
                for _ in range(3)
            ]
        assert [reply.status_code for reply in replies] == [401, 401, 429]
        assert len(calls) == 2
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("operation", ["refresh", "logout"])
def test_signed_token_with_wrong_persisted_hash_cannot_revoke_a_family(db, operation):
    from datetime import timedelta

    from app.core.security import TokenType, create_token
    from app.models.user import RefreshToken, RefreshTokenFamily

    user = create_user(db)
    initial = sign_in(db)
    payload = auth.decode_refresh_token(initial.refresh_token)
    forged = create_token(
        user.id, TokenType.REFRESH, expires_delta=timedelta(minutes=1), jti=payload["jti"]
    )
    assert forged != initial.refresh_token
    if operation == "refresh":
        with pytest.raises(HTTPException) as exc:
            rotate(db, forged)
        assert exc.value.status_code == 401
    else:
        assert (
            auth.logout(RefreshTokenRequest(refresh_token=forged), Response(), db).status_code
            == 204
        )
    assert all(family.revoked_at is None for family in db.scalars(select(RefreshTokenFamily)))
    rows = list(db.scalars(select(RefreshToken)))
    assert all(
        len(row.token_hash) == 64 and row.token_hash not in {forged, initial.refresh_token}
        for row in rows
    )
    assert rotate(db, initial.refresh_token).refresh_token


def test_login_audit_failure_leaves_no_family_or_cookies(db, monkeypatch):
    from app.models.user import RefreshToken, RefreshTokenFamily

    create_user(db)
    response = Response()

    def fail(*args, **kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(auth.AuditService, "record", fail)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        auth.login(LoginRequest(email="user@example.com", password=PASSWORD), response, db)
    assert not list(db.scalars(select(RefreshToken)))
    assert not list(db.scalars(select(RefreshTokenFamily)))
    assert not response.headers.getlist("set-cookie")
