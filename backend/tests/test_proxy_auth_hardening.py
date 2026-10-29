"""Explicit proxy boundaries; malformed chains never become caller identities."""

import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import Request

from app.core.rate_limit import InMemoryRateLimitMiddleware, RedisRateLimitMiddleware, get_client_ip
from tests.test_rate_limit import FakeRedis


def proxy_request(peer, headers):
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers,
            "client": (peer, 1234) if peer is not None else None,
            "scheme": "http",
            "server": ("test", 80),
            "query_string": b"",
        }
    )


@pytest.mark.parametrize(
    ("peer", "chain", "trusted", "expected"),
    [
        ("198.51.100.8", "203.0.113.1", ["10.0.0.0/24"], "198.51.100.8"),
        ("10.0.0.8", "203.0.113.1", [], "10.0.0.8"),
        ("10.0.0.8", "203.0.113.1", ["10.0.0.0/24"], "203.0.113.1"),
        ("10.0.0.8", "192.0.2.99, 203.0.113.1", ["10.0.0.0/24"], "203.0.113.1"),
        (
            "10.0.0.8",
            "192.0.2.99, 203.0.113.1, 10.0.1.8",
            ["10.0.0.0/24", "10.0.1.0/24"],
            "203.0.113.1",
        ),
        ("10.0.0.8", "192.0.2.99, 203.0.113.1, 10.0.1.8", ["10.0.0.0/24"], "10.0.1.8"),
        (
            "2001:db8:1::8",
            "2001:db8:ffff::99, 2001:db8:2::3, 2001:db8:1::9",
            ["2001:db8:1::/64"],
            "2001:db8:2::3",
        ),
        ("2001:0db8:0002::3", "192.0.2.1", [], "2001:db8:2::3"),
        ("10.0.0.8", "203.0.113.1,", ["10.0.0.0/24"], "10.0.0.8"),
        ("10.0.0.8", ",203.0.113.1", ["10.0.0.0/24"], "10.0.0.8"),
        ("10.0.0.8", "203.0.113.1,,10.0.0.2", ["10.0.0.0/24"], "10.0.0.8"),
        ("10.0.0.8", "203.0.113.1, not-an-ip", ["10.0.0.0/24"], "10.0.0.8"),
        ("10.0.0.8", "203.0.113.1:1234", ["10.0.0.0/24"], "10.0.0.8"),
        ("10.0.0.8", "[2001:db8::1]:1234", ["10.0.0.0/24"], "10.0.0.8"),
        ("10.0.0.8", "203.0.113.1, fe80::1%eth0", ["10.0.0.0/24"], "10.0.0.8"),
        ("10.0.0.8", "10.0.0.2, 10.0.0.3", ["10.0.0.0/24"], "10.0.0.8"),
        ("10.0.0.8", ",".join(["203.0.113.1"] * 33), ["10.0.0.0/24"], "10.0.0.8"),
        ("10.0.0.8", " " * 4096 + "203.0.113.1", ["10.0.0.0/24"], "10.0.0.8"),
        (None, "203.0.113.1", ["10.0.0.0/24"], "unknown"),
    ],
)
def test_forwarding_chain_policy(peer, chain, trusted, expected):
    request = proxy_request(peer, [(b"x-forwarded-for", chain.encode())])
    assert get_client_ip(request, trusted) == expected


def test_duplicate_forwarding_headers_are_not_selected_arbitrarily():
    request = proxy_request(
        "10.0.0.8", [(b"x-forwarded-for", b"203.0.113.1"), (b"x-forwarded-for", b"198.51.100.1")]
    )
    assert get_client_ip(request, ["10.0.0.0/24"]) == "10.0.0.8"


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"x-forwarded-proto", b"https,http")],
        [(b"x-forwarded-proto", b"https"), (b"x-forwarded-proto", b"http")],
        [(b"x-forwarded-proto", b"javascript")],
    ],
)
def test_missing_or_ambiguous_scheme_is_not_applied(headers):
    from app.core.rate_limit import get_trusted_forwarded_scheme

    assert get_trusted_forwarded_scheme(proxy_request("10.0.0.8", headers), ["10.0.0.0/24"]) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("middleware", [InMemoryRateLimitMiddleware, RedisRateLimitMiddleware])
async def test_spoofed_prefix_does_not_rotate_rate_limit_buckets(middleware):
    app = FastAPI()
    app.state.redis = FakeRedis()
    app.add_middleware(middleware, requests_per_minute=1, trusted_proxy_cidrs=["10.0.0.0/24"])

    @app.get("/")
    async def index():
        return {"ok": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("10.0.0.8", 1234)), base_url="http://test"
    ) as client:
        first = await client.get("/", headers={"X-Forwarded-For": "192.0.2.1, 203.0.113.7"})
        second = await client.get("/", headers={"X-Forwarded-For": "192.0.2.2, 203.0.113.7"})
    assert first.status_code == 200
    assert second.status_code == 429


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("peer", "expected_scheme"), [("10.0.0.8", "https"), ("198.51.100.8", "http")]
)
async def test_trusted_scheme_preserves_https_redirects_without_trusting_client_ip_rewrite(
    monkeypatch, peer, expected_scheme
):
    from app.core.config import settings
    from app.main import create_app

    monkeypatch.setattr(settings, "trusted_proxy_cidrs", ["10.0.0.0/24"])
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(peer, 1234)), base_url="http://test"
    ) as client:
        response = await client.get("/health/", headers={"X-Forwarded-Proto": "https"})
    assert response.status_code == 307
    assert response.headers["location"] == f"{expected_scheme}://test/health"
