"""Identifier budgets use the same public responses for existing/absent accounts."""

import asyncio
import os
from uuid import uuid4

import httpx
import pytest
from fastapi import Depends, FastAPI, HTTPException
from starlette.requests import Request

from app.core import login_throttle
from app.core.config import settings
from app.core.redis import create_redis_client
from app.schemas.auth import LoginRequest


@pytest.mark.asyncio
@pytest.mark.parametrize("backend", ["memory", "redis"])
async def test_account_budget_concurrent_requests_expire_without_extending_denials(
    monkeypatch, backend
):
    monkeypatch.setattr(settings, "rate_limit_backend", backend)
    monkeypatch.setattr(settings, "login_account_rate_limit_per_minute", 3)
    clock = [60000.0]
    monkeypatch.setattr(login_throttle, "time", lambda: clock[0])
    email = f"quota-{uuid4().hex}@example.com"
    redis = None
    app = FastAPI()
    if backend == "redis":
        url = os.getenv("TEST_REDIS_URL")
        if not url:
            pytest.skip("TEST_REDIS_URL required for real shared account-quota atomicity")
        redis = create_redis_client(url)
        app.state.redis = redis
    calls = []

    @app.post("/login", dependencies=[Depends(login_throttle.enforce_login_account_limit)])
    async def endpoint(payload: LoginRequest):
        calls.append(str(payload.email))
        return {"accepted": True}

    identity = login_throttle.account_identifier(email)
    assert len(identity) == 64 and email not in identity
    assert login_throttle.account_identifier(email.upper()) == identity
    keys = [f"login-account:{identity}:{window}" for window in (1000, 1001)]

    async def send(index):
        transport = httpx.ASGITransport(app=app, client=(f"198.51.100.{index + 1}", 1234))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/login", json={"email": email, "password": "bad-password"})

    try:
        replies = await asyncio.gather(*(send(index) for index in range(10)))
        assert [reply.status_code for reply in replies].count(200) == 3
        assert [reply.status_code for reply in replies].count(429) == 7
        assert len(calls) == 3
        assert all(
            reply.headers["Retry-After"] == "60" for reply in replies if reply.status_code == 429
        )
        if redis is not None:
            assert await redis.get(keys[0]) == "3"
            assert 0 < await redis.pttl(keys[0]) <= 60000
            await redis.pexpire(keys[0], 30000)
            assert (await send(0)).status_code == 429
            assert 0 < await redis.pttl(keys[0]) <= 30000
        clock[0] += 60
        assert (await send(0)).status_code == 200
    finally:
        if redis is not None:
            await redis.delete(*keys)
            await redis.aclose()


@pytest.mark.asyncio
async def test_redis_outage_fails_closed_without_memory_fallback(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    request = Request({"type": "http", "app": FastAPI(), "headers": []})
    with pytest.raises(HTTPException) as exc:
        await login_throttle.enforce_login_account_limit(
            LoginRequest(email="user@example.com", password="bad"), request
        )
    assert exc.value.status_code == 503 and exc.value.headers == {"Retry-After": "1"}
    assert not hasattr(request.app.state, "login_account_buckets")


@pytest.mark.asyncio
async def test_memory_identifier_storage_is_bounded_and_recovers(monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_backend", "memory")
    monkeypatch.setattr(login_throttle, "MAX_MEMORY_IDENTIFIERS", 2)
    clock = [60000.0]
    monkeypatch.setattr(login_throttle, "time", lambda: clock[0])
    request = Request({"type": "http", "app": FastAPI(), "headers": []})
    for local in ("one", "two"):
        await login_throttle.enforce_login_account_limit(
            LoginRequest(email=f"{local}@example.com", password="bad"), request
        )
    with pytest.raises(HTTPException) as exc:
        await login_throttle.enforce_login_account_limit(
            LoginRequest(email="three@example.com", password="bad"), request
        )
    assert exc.value.status_code == 503
    assert len(request.app.state.login_account_buckets) == 2
    clock[0] += 60
    await login_throttle.enforce_login_account_limit(
        LoginRequest(email="three@example.com", password="bad"), request
    )
    assert len(request.app.state.login_account_buckets) == 1
