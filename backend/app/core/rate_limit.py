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
    peer = request.client.host if request.client else "unknown"
    try:
        peer_address = ip_address(peer)
    except ValueError:
        return peer

    trusted = any(
        peer_address in ip_network(cidr, strict=False) for cidr in trusted_proxy_cidrs
    )
    if not trusted:
        return peer

    forwarded_for = request.headers.get("x-forwarded-for")
    if not forwarded_for:
        return peer

    candidate = forwarded_for.split(",", maxsplit=1)[0].strip()
    try:
        return str(ip_address(candidate))
    except ValueError:
        return peer


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
