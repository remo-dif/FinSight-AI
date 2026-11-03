"""Protocol invariants beyond browser header ordering."""

import asyncio
from datetime import timedelta

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session

from app.api.routes import auth
from app.core.database import get_db
from app.core.security import TokenType, create_token, get_current_user_async
from app.main import create_app
from app.schemas.auth import LoginRequest, RefreshTokenRequest
from tests import test_auth as auth_fixtures
from tests import test_case_workflow_postgres as pg_fixtures
from tests.test_auth import create_user

db = auth_fixtures.db
case_pg = pg_fixtures.case_pg


@pytest.mark.asyncio
async def test_bound_cookies_are_httponly_secure_and_selector_is_login_only(db, monkeypatch):
    user = create_user(db)
    monkeypatch.setattr(auth.settings, "app_env", "production")
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://test"
    ) as client:
        login = await client.post(
            "/api/auth/login",
            json={"email": user.email, "password": "correct horse battery staple"},
            headers={"X-FinSight-Cookie-Session": "true"},
        )
        assert login.status_code == 200
        assert login.json()["refresh_token"] == ""
        binding = client.cookies.get("__Host-finsight_session")
        assert len(binding) == 32
        live_cookies = [c for c in login.headers.get_list("set-cookie") if "Max-Age=0" not in c]
        assert len(live_cookies) == 3
        assert all("HttpOnly" in c and "Secure" in c and "SameSite=lax" in c for c in live_cookies)
        expired = create_token(
            user.id, TokenType.ACCESS, timedelta(seconds=-1), session_id=auth.UUID(binding)
        )
        refreshed = await client.post(
            "/api/auth/refresh", json={}, headers={"Authorization": f"Bearer {expired}"}
        )
        assert refreshed.status_code == 200
        assert refreshed.json()["refresh_token"] == ""
        assert not any(
            c.startswith("__Host-finsight_session=")
            for c in refreshed.headers.get_list("set-cookie")
        )
        late_access = refreshed.json()["access_token"]
        out = await client.post("/api/auth/logout", json={})
        assert out.status_code == 204
        assert not any(
            c.startswith("__Host-finsight_session=") for c in out.headers.get_list("set-cookie")
        )
        assert (
            await client.get("/api/auth/me", headers={"Authorization": f"Bearer {late_access}"})
        ).status_code == 401


@pytest.mark.asyncio
async def test_selector_mismatch_fails_before_consuming_either_family(db):
    user = create_user(db)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            "/api/auth/login",
            json={"email": user.email, "password": "correct horse battery staple"},
        )
        a = client.cookies.get("finsight_session")
        a_token = client.cookies.get(f"finsight_refresh_{a}")
        second = await client.post(
            "/api/auth/login",
            json={"email": user.email, "password": "correct horse battery staple"},
        )
        b = client.cookies.get("finsight_session")
        client.cookies.set(f"finsight_refresh_{b}", a_token, domain="test.local", path="/api/auth")
        assert (await client.post("/api/auth/refresh", json={})).status_code == 401
        # The rejected mismatch did not consume A; explicit JSON-token clients still rotate.
        rotated = await client.post(
            "/api/auth/refresh", json={"refresh_token": first.json()["refresh_token"]}
        )
        assert rotated.status_code == 200
        assert bool(rotated.json()["refresh_token"])
        assert (
            await client.get(
                "/api/auth/me", headers={"Authorization": f"Bearer {second.json()['access_token']}"}
            )
        ).status_code == 200


def test_async_authorization_rejects_revoked_bound_access(case_pg):
    engine, _ = case_pg
    with Session(engine) as db:
        user = create_user(db)
        signed = auth.login(
            LoginRequest(email=user.email, password="correct horse battery staple"),
            auth.Response(),
            db,
        )
        schema = db.scalar(text("select current_schema()"))
        auth.logout(RefreshTokenRequest(refresh_token=signed.refresh_token), auth.Response(), db)

    async def verify():
        async_engine = create_async_engine(
            engine.url, connect_args={"options": f"-csearch_path={schema},public"}
        )
        try:
            async with AsyncSession(async_engine) as db:
                with pytest.raises(HTTPException) as failure:
                    await get_current_user_async(signed.access_token, db)
                assert failure.value.status_code == 401
        finally:
            await async_engine.dispose()

    # Psycopg async I/O requires a selector loop on Windows, without changing global policy.
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(verify())


@pytest.mark.asyncio
async def test_duplicate_selector_is_rejected_before_authentication(db):
    user = create_user(db)
    response = auth.Response()
    tokens = auth.login(
        LoginRequest(email=user.email, password="correct horse battery staple"), response, db
    )
    selector = next(
        value.split(";", 1)[0]
        for value in response.headers.getlist("set-cookie")
        if value.startswith("finsight_session=")
    )
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        headers = [
            ("Cookie", selector),
            ("Cookie", selector),
            ("Authorization", f"Bearer {tokens.access_token}"),
        ]
        for path in ("refresh", "logout"):
            result = await client.post(f"/api/auth/{path}", json={}, headers=headers)
            assert result.status_code == 401
            assert result.json()["detail"] == "Ambiguous session cookies"
        result = await client.get("/api/auth/me", headers=headers)
        assert result.status_code == 401
        assert result.json()["detail"] == "Ambiguous session cookies"
