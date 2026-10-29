import hashlib
import logging
from collections import defaultdict, deque
from ipaddress import ip_address, ip_network
from time import monotonic, time

from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return current
"""

EXCLUDED_PATHS = frozenset({"/health", "/readyz"})


def get_client_ip(request: Request, trusted_proxy_cidrs: list[str]) -> str:
    """Resolve the first untrusted hop, provided ASGI client is the socket peer.

    Malformed/ambiguous chains collapse to the peer, never a header-selected IP.
    Uvicorn proxy-header rewriting must be disabled (see the image command).
    """
    peer = request.client.host if request.client else "unknown"
    try:
        peer_address = ip_address(peer)
        networks = [ip_network(cidr, strict=False) for cidr in trusted_proxy_cidrs]
    except ValueError:
        return peer
    fallback = str(peer_address)
    if not any(peer_address in network for network in networks):
        return fallback

    headers = request.headers.getlist("x-forwarded-for")
    if len(headers) != 1 or len(headers[0]) > 4096:
        return fallback
    hops = [hop.strip() for hop in headers[0].split(",")]
    if len(hops) > 32 or any(not hop or "%" in hop for hop in hops):
        return fallback
    try:
        addresses = [ip_address(hop) for hop in hops]
    except ValueError:
        return fallback
    for address in reversed(addresses):
        if not any(address in network for network in networks):
            return str(address)
    # An all-trusted chain does not establish an untrusted client boundary.
    return fallback


def get_trusted_forwarded_scheme(request: Request, trusted_proxy_cidrs: list[str]) -> str | None:
    """Keep HTTPS redirects without allowing a second client-IP rewrite layer."""
    if request.client is None:
        return None
    try:
        peer = ip_address(request.client.host)
        trusted = any(peer in ip_network(cidr, strict=False) for cidr in trusted_proxy_cidrs)
    except ValueError:
        return None
    values = request.headers.getlist("x-forwarded-proto")
    if trusted and len(values) == 1 and values[0] in {"http", "https"}:
        return values[0]
    return None


class InMemoryRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        requests_per_minute: int = 120,
        trusted_proxy_cidrs: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.trusted_proxy_cidrs = trusted_proxy_cidrs or []
        self.requests: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in EXCLUDED_PATHS:
            return await call_next(request)

        client = get_client_ip(request, self.trusted_proxy_cidrs)
        now = monotonic()
        bucket = self.requests[client]
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= self.requests_per_minute:
            return _limit_response()
        bucket.append(now)
        return await call_next(request)


class RedisRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        requests_per_minute: int = 120,
        trusted_proxy_cidrs: list[str] | None = None,
    ) -> None:
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.trusted_proxy_cidrs = trusted_proxy_cidrs or []

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in EXCLUDED_PATHS:
            return await call_next(request)

        client = get_client_ip(request, self.trusted_proxy_cidrs)
        identity = hashlib.sha256(client.encode("utf-8")).hexdigest()
        window = int(time() // 60)
        key = f"rate-limit:{identity}:{window}"

        try:
            current = int(
                await request.app.state.redis.eval(RATE_LIMIT_SCRIPT, 1, key, 60)
            )
        except (AttributeError, RedisError):
            logger.exception("Redis rate-limit storage is unavailable")
            return JSONResponse(
                {"detail": "Rate-limit service unavailable"},
                status_code=503,
                headers={"Retry-After": "1"},
            )

        if current > self.requests_per_minute:
            return _limit_response()

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(self.requests_per_minute)
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, self.requests_per_minute - current)
        )
        return response


def _limit_response() -> JSONResponse:
    return JSONResponse(
        {"detail": "Rate limit exceeded"},
        status_code=429,
        headers={"Retry-After": "60"},
    )
