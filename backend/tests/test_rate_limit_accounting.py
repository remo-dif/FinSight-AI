"""Quota accounting, exact window expiry, concurrency and storage failure contracts."""

import asyncio
import hashlib
import os
from ipaddress import ip_address
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel
from redis.exceptions import RedisError
from starlette.responses import JSONResponse

from app.core.rate_limit import InMemoryRateLimitMiddleware, RedisRateLimitMiddleware
from app.core.redis import create_redis_client
from tests.test_rate_limit import FakeRedis

MIDDLEWARES = [InMemoryRateLimitMiddleware, RedisRateLimitMiddleware]


class LoginAttempt(BaseModel):
    accepted: bool


def quota_app(middleware, *, global_limit=50, login_limit=10, redis=None):
    app = FastAPI()
    app.state.redis = redis if redis is not None else FakeRedis()
    app.add_middleware(
        middleware,
        requests_per_minute=global_limit,
        login_requests_per_minute=login_limit,
    )
    calls = []

    @app.post("/api/auth/login")
    async def login(attempt: LoginAttempt):
        calls.append("login")
        return JSONResponse(
            {"detail": "ok" if attempt.accepted else "Invalid email or password"},
            status_code=200 if attempt.accepted else 401,
        )

    @app.get("/ordinary")
    async def ordinary():
        calls.append("ordinary")
        return {"ok": True}

    return app, calls


def quota_client(app, ip="203.0.113.10"):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(ip, 1234)), base_url="http://test"
    )


def controlled_clock(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("app.core.rate_limit.monotonic", lambda: clock[0])
    monkeypatch.setattr("app.core.rate_limit.time", lambda: clock[0])
    return clock


@pytest.mark.asyncio
@pytest.mark.parametrize("middleware", MIDDLEWARES)
@pytest.mark.parametrize(
    ("payload", "status_code"), [({"accepted": True}, 200), ({"accepted": False}, 401), ({}, 422)]
)
async def test_all_login_outcomes_and_login_denials_consume_global_budget(
    monkeypatch, middleware, payload, status_code
):
    controlled_clock(monkeypatch)
    app, calls = quota_app(middleware, global_limit=2, login_limit=1)
    async with quota_client(app) as client:
        assert (await client.post("/api/auth/login", json=payload)).status_code == status_code
        denied_login = await client.post("/api/auth/login", json={"accepted": True})
        denied_general = await client.get("/ordinary")
    assert denied_login.status_code == denied_general.status_code == 429
    assert denied_login.json() == {"detail": "Rate limit exceeded"}
    assert denied_login.headers["Retry-After"] == "60"
    # A malformed request is charged before validation but never reaches the handler.
    assert calls == ([] if status_code == 422 else ["login"])


@pytest.mark.asyncio
@pytest.mark.parametrize("middleware", MIDDLEWARES)
async def test_non_login_requests_do_not_spend_login_quota(monkeypatch, middleware):
    controlled_clock(monkeypatch)
    app, calls = quota_app(middleware, global_limit=4, login_limit=1)
    async with quota_client(app) as client:
        assert (await client.get("/ordinary")).status_code == 200
        assert (await client.post("/api/auth/login", json={"accepted": False})).status_code == 401
        assert (await client.post("/api/auth/login", json={"accepted": False})).status_code == 429
        assert (await client.get("/ordinary")).status_code == 200
        assert (await client.get("/ordinary")).status_code == 429
    assert calls == ["ordinary", "login", "ordinary"]


@pytest.mark.asyncio
@pytest.mark.parametrize("middleware", MIDDLEWARES)
async def test_window_expires_at_exactly_sixty_seconds(monkeypatch, middleware):
    clock = controlled_clock(monkeypatch)
    app, calls = quota_app(middleware, global_limit=1)
    async with quota_client(app) as client:
        assert (await client.get("/ordinary")).status_code == 200
        clock[0] = 60.0
        assert (await client.get("/ordinary")).status_code == 200
    assert calls == ["ordinary", "ordinary"]


@pytest.mark.asyncio
@pytest.mark.parametrize("middleware", MIDDLEWARES)
async def test_denied_general_attempts_do_not_extend_the_window(monkeypatch, middleware):
    clock = controlled_clock(monkeypatch)
    app, calls = quota_app(middleware, global_limit=1)
    async with quota_client(app) as client:
        assert (await client.get("/ordinary")).status_code == 200
        for instant in (1.0, 30.0, 59.999):
            clock[0] = instant
            assert (await client.get("/ordinary")).status_code == 429
        clock[0] = 60.0
        assert (await client.get("/ordinary")).status_code == 200
    assert calls == ["ordinary", "ordinary"]


@pytest.mark.asyncio
@pytest.mark.parametrize("middleware", MIDDLEWARES)
async def test_denied_login_attempts_do_not_extend_the_login_window(monkeypatch, middleware):
    clock = controlled_clock(monkeypatch)
    app, calls = quota_app(middleware, global_limit=50, login_limit=1)
    async with quota_client(app) as client:
        assert (await client.post("/api/auth/login", json={"accepted": True})).status_code == 200
        for instant in (1.0, 30.0, 59.999):
            clock[0] = instant
            assert (
                await client.post("/api/auth/login", json={"accepted": True})
            ).status_code == 429
        clock[0] = 60.0
        assert (await client.post("/api/auth/login", json={"accepted": True})).status_code == 200
    assert calls == ["login", "login"]


@pytest.mark.asyncio
@pytest.mark.parametrize("middleware", MIDDLEWARES)
@pytest.mark.parametrize(("global_limit", "login_limit"), [(5, 50), (50, 5)])
async def test_concurrent_requests_are_bounded_by_each_quota(
    monkeypatch, middleware, global_limit, login_limit
):
    controlled_clock(monkeypatch)
    app, calls = quota_app(middleware, global_limit=global_limit, login_limit=login_limit)
    async with quota_client(app) as client:
        responses = await asyncio.gather(
            *(client.post("/api/auth/login", json={"accepted": True}) for _ in range(16))
        )
    assert [response.status_code for response in responses].count(200) == 5
    assert [response.status_code for response in responses].count(429) == 11
    assert calls == ["login"] * 5


@pytest.mark.asyncio
@pytest.mark.parametrize("middleware", MIDDLEWARES)
async def test_successful_responses_report_the_same_general_quota_headers(monkeypatch, middleware):
    controlled_clock(monkeypatch)
    app, _ = quota_app(middleware, global_limit=3)
    async with quota_client(app) as client:
        first = await client.get("/ordinary")
        second = await client.get("/ordinary")
    assert first.headers["X-RateLimit-Limit"] == second.headers["X-RateLimit-Limit"] == "3"
    assert first.headers["X-RateLimit-Remaining"] == "2"
    assert second.headers["X-RateLimit-Remaining"] == "1"


class UnavailableOnLoginBudget(FakeRedis):
    async def eval(self, script, numkeys, key, ttl, limit):
        if key.startswith("login-rate-limit:"):
            raise RedisError("synthetic second-budget failure")
        return await super().eval(script, numkeys, key, ttl, limit)


@pytest.mark.asyncio
async def test_second_redis_budget_failure_is_closed_without_running_login(monkeypatch):
    controlled_clock(monkeypatch)
    redis = UnavailableOnLoginBudget()
    app, calls = quota_app(RedisRateLimitMiddleware, redis=redis)
    async with quota_client(app) as client:
        response = await client.post("/api/auth/login", json={"accepted": True})
    assert response.status_code == 503
    assert response.json() == {"detail": "Rate-limit service unavailable"}
    assert response.headers["Retry-After"] == "1"
    assert calls == []
    assert len(redis.counts) == 1
    assert list(redis.counts.values()) == [1]


@pytest.mark.asyncio
@pytest.mark.parametrize(("global_limit", "login_limit"), [(5, 50), (50, 5)])
async def test_real_redis_concurrency_and_rejections_do_not_refresh_ttl(
    monkeypatch, global_limit, login_limit
):
    url = os.getenv("TEST_REDIS_URL")
    if not url:
        pytest.skip("TEST_REDIS_URL required for real quota concurrency and TTL validation")
    clock = controlled_clock(monkeypatch)
    clock[0] = 60000.0
    unique_ip = str(ip_address(int(ip_address("2001:db8::")) | (uuid4().int & ((1 << 64) - 1))))
    identity = hashlib.sha256(unique_ip.encode()).hexdigest()
    keys = [f"{prefix}:{identity}:1000" for prefix in ("rate-limit", "login-rate-limit")]
    redis = create_redis_client(url)
    app, calls = quota_app(
        RedisRateLimitMiddleware, global_limit=global_limit, login_limit=login_limit, redis=redis
    )
    try:
        async with quota_client(app, unique_ip) as client:
            responses = await asyncio.gather(
                *(client.post("/api/auth/login", json={"accepted": True}) for _ in range(16))
            )
            assert [response.status_code for response in responses].count(200) == 5
            assert [response.status_code for response in responses].count(429) == 11
            assert calls == ["login"] * 5
            assert await redis.get(keys[0]) == str(min(16, global_limit))
            assert await redis.get(keys[1]) == str(min(16, global_limit, login_limit))
            for key in keys:
                assert 0 < await redis.pttl(key) <= 60000
                # Shorten only this test's keys. A buggy reset to 60s is detectable
                # without sleeps or comparing fragile wall-clock durations.
                assert await redis.pexpire(key, 30000)
            assert (
                await client.post("/api/auth/login", json={"accepted": True})
            ).status_code == 429
            for key in keys:
                assert 0 < await redis.pttl(key) <= 30000
    finally:
        await redis.delete(*keys)
        await redis.aclose()
