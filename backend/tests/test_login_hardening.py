import hashlib
import os
from ipaddress import ip_address
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import func, select
from starlette.responses import JSONResponse, Response

from app.api.routes import auth
from app.core import security
from app.core.rate_limit import InMemoryRateLimitMiddleware, RedisRateLimitMiddleware
from app.core.redis import create_redis_client
from app.models.user import RefreshToken
from app.schemas.auth import LoginRequest, RegisterRequest
from tests import test_auth as auth_fixture_module
from tests.test_auth import create_user
from tests.test_rate_limit import FakeRedis

db = auth_fixture_module.db


@pytest.mark.parametrize(
    ("state", "verification"),
    [
        ("missing", False),
        ("missing", True),
        ("inactive", False),
        ("inactive", True),
        ("active", False),
    ],
)
def test_failed_login_always_verifies_once_and_never_issues_tokens(
    db, monkeypatch, state, verification
):
    user = None if state == "missing" else create_user(db)
    if state == "inactive":
        user.is_active = False
        db.commit()
    calls = []

    def verify(password, hashed):
        calls.append((password, hashed))
        return verification

    monkeypatch.setattr(auth, "verify_password", verify)
    response = Response()
    with pytest.raises(HTTPException) as exc:
        auth.login(
            LoginRequest(email="user@example.com", password="synthetic password"), response, db
        )
    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid email or password"
    assert len(calls) == 1
    if state == "active":
        assert calls[0][1] == user.password_hash
    else:
        assert calls[0][1] == security.DUMMY_PASSWORD_HASH
    assert not response.headers.getlist("set-cookie")
    assert db.scalar(select(func.count()).select_from(RefreshToken)) == 0


def test_dummy_hash_is_valid_bcrypt_with_current_hashing_cost():
    import bcrypt

    hashed = security.DUMMY_PASSWORD_HASH
    assert isinstance(bcrypt.checkpw(b"synthetic non-secret", hashed.encode()), bool)
    assert hashed.split("$")[1:3] == security.hash_password("synthetic non-secret").split("$")[1:3]


def test_registration_enumeration_contract_remains_explicit(db):
    create_user(db)
    with pytest.raises(HTTPException) as exc:
        auth.register(
            RegisterRequest(
                email="user@example.com", password="synthetic password", full_name="Synthetic"
            ),
            db,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail == "Email is already registered"


@pytest.mark.asyncio
@pytest.mark.parametrize("middleware", [InMemoryRateLimitMiddleware, RedisRateLimitMiddleware])
async def test_login_ip_budget_is_separate_bounded_and_recovers(monkeypatch, middleware):
    clock = [0.0]
    monkeypatch.setattr("app.core.rate_limit.monotonic", lambda: clock[0])
    monkeypatch.setattr("app.core.rate_limit.time", lambda: clock[0])
    app = FastAPI()
    redis = FakeRedis()
    app.state.redis = redis
    app.add_middleware(middleware, requests_per_minute=50)

    @app.post("/api/auth/login")
    async def login():
        return JSONResponse({"detail": "Invalid email or password"}, status_code=401)

    @app.get("/ordinary")
    async def ordinary():
        return {"ok": True}

    async def client_request(ip, path="/api/auth/login", email="target@example.invalid"):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=(ip, 1234)), base_url="http://test"
        ) as client:
            return (
                await client.post(path, json={"email": email, "password": "synthetic"})
                if path.endswith("login")
                else await client.get(path)
            )

    for index in range(10):
        assert (
            await client_request("203.0.113.7", email=f"synthetic-{index}@example.invalid")
        ).status_code == 401
    limited = await client_request("203.0.113.7")
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    assert (await client_request("203.0.113.7", "/ordinary")).status_code == 200
    # The same account from another IP is not locked by somebody else's attempts.
    assert (await client_request("203.0.113.8")).status_code == 401
    clock[0] = 61.0
    assert (await client_request("203.0.113.7")).status_code == 401
    assert "@" not in " ".join(redis.counts)


@pytest.mark.asyncio
async def test_login_budget_uses_real_redis_expiry_and_never_extends_account_lock(monkeypatch):
    url = os.getenv("TEST_REDIS_URL")
    if not url:
        pytest.skip("TEST_REDIS_URL required for the service-backed login budget test")
    clock = [60000.0]
    monkeypatch.setattr("app.core.rate_limit.time", lambda: clock[0])
    suffix = uuid4().hex[:8]
    ip = str(ip_address(f"2001:db8::{suffix[:4]}:{suffix[4:]}"))
    identity = hashlib.sha256(ip.encode()).hexdigest()
    redis = create_redis_client(url)
    app = FastAPI()
    app.state.redis = redis
    app.add_middleware(
        RedisRateLimitMiddleware, requests_per_minute=50, login_requests_per_minute=2
    )

    @app.post("/api/auth/login")
    async def login():
        return JSONResponse({"detail": "Invalid email or password"}, status_code=401)

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=(ip, 1234)), base_url="http://test"
        ) as client:
            assert (await client.post("/api/auth/login")).status_code == 401
            assert (await client.post("/api/auth/login")).status_code == 401
            assert (await client.post("/api/auth/login")).status_code == 429
            key = f"login-rate-limit:{identity}:1000"
            assert 0 < await redis.ttl(key) <= 60
            clock[0] += 61
            assert (await client.post("/api/auth/login")).status_code == 401
    finally:
        for prefix in ("rate-limit", "login-rate-limit"):
            keys = [key async for key in redis.scan_iter(match=f"{prefix}:{identity}:*")]
            if keys:
                await redis.delete(*keys)
        await redis.aclose()
