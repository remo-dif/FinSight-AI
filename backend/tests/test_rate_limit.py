from collections import defaultdict
import hashlib
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from redis.exceptions import RedisError

import app.main as main_module
from app.core.config import Settings
from app.core.rate_limit import RedisRateLimitMiddleware
from app.core.redis import create_redis_client


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = defaultdict(int)
        self.pings = 0
        self.closed = False

    async def eval(self, _script: str, _numkeys: int, key: str, _ttl: int) -> int:
        self.counts[key] += 1
        return self.counts[key]

    async def ping(self) -> bool:
        self.pings += 1
        return True

    async def aclose(self) -> None:
        self.closed = True


class UnavailableRedis(FakeRedis):
    async def eval(self, _script: str, _numkeys: int, key: str, _ttl: int) -> int:
        raise RedisError("unavailable")


def rate_limited_app(redis, *, trusted_proxy_cidrs: list[str]) -> FastAPI:
    app = FastAPI()
    app.state.redis = redis
    app.add_middleware(
        RedisRateLimitMiddleware,
        requests_per_minute=1,
        trusted_proxy_cidrs=trusted_proxy_cidrs,
    )

    @app.get("/")
    async def index() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


@pytest.mark.asyncio
async def test_redis_rate_limit_is_shared_by_forwarded_client_ip() -> None:
    app = rate_limited_app(FakeRedis(), trusted_proxy_cidrs=["127.0.0.1/32"])
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.get("/", headers={"X-Forwarded-For": "203.0.113.10"})
        limited = await client.get("/", headers={"X-Forwarded-For": "203.0.113.10"})
        other_client = await client.get("/", headers={"X-Forwarded-For": "203.0.113.11"})

    assert first.status_code == 200
    assert first.headers["X-RateLimit-Remaining"] == "0"
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"
    assert other_client.status_code == 200


@pytest.mark.asyncio
async def test_untrusted_peer_cannot_spoof_forwarded_client_ip() -> None:
    app = rate_limited_app(FakeRedis(), trusted_proxy_cidrs=["127.0.0.1/32"])
    transport = httpx.ASGITransport(app=app, client=("198.51.100.20", 1234))

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.get("/", headers={"X-Forwarded-For": "203.0.113.10"})
        limited = await client.get("/", headers={"X-Forwarded-For": "203.0.113.11"})

    assert first.status_code == 200
    assert limited.status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_returns_503_when_redis_is_unavailable() -> None:
    app = rate_limited_app(UnavailableRedis(), trusted_proxy_cidrs=[])
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
        health = await client.get("/health")

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"
    assert health.status_code == 200


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, _query) -> None:
        return None


class FakeEngine:
    def connect(self) -> FakeConnection:
        return FakeConnection()


@pytest.mark.asyncio
async def test_redis_lifecycle_and_readiness(monkeypatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(main_module.settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(main_module.settings, "upload_dir", Path.cwd())
    monkeypatch.setattr(main_module, "create_redis_client", lambda _url: redis)
    monkeypatch.setattr(main_module, "engine", FakeEngine())
    app = main_module.create_app()

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/readyz")

        assert response.status_code == 200
        assert redis.pings == 2
        assert not redis.closed

    assert redis.closed


def test_redis_and_proxy_settings_parse_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "redis")
    monkeypatch.setenv("TRUSTED_PROXY_CIDRS", "10.0.0.0/16,127.0.0.1/32")
    configured = Settings(
        DATABASE_URL="sqlite:///./test.db",
        JWT_SECRET_KEY="test-access-secret-that-is-long-enough-123",
        JWT_REFRESH_SECRET_KEY="test-refresh-secret-that-is-long-enough-456",
        OPENAI_API_KEY="test-openai-key",
    )

    assert configured.rate_limit_backend == "redis"
    assert configured.trusted_proxy_cidrs == ["10.0.0.0/16", "127.0.0.1/32"]


@pytest.mark.asyncio
async def test_rate_limit_against_real_redis() -> None:
    redis_url = os.getenv("TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("TEST_REDIS_URL is not configured")

    redis = create_redis_client(redis_url)
    client_ip = f"203.0.113.{uuid4().int % 254 + 1}"
    identity = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()
    app = rate_limited_app(redis, trusted_proxy_cidrs=["127.0.0.1/32"])
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))

    try:
        await redis.ping()
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.get("/", headers={"X-Forwarded-For": client_ip})
            limited = await client.get("/", headers={"X-Forwarded-For": client_ip})

        assert first.status_code == 200
        assert limited.status_code == 429
    finally:
        keys = [key async for key in redis.scan_iter(match=f"rate-limit:{identity}:*")]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()
