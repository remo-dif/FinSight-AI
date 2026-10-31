"""Temporary, non-enumerating identifier quota; IP quotas remain in middleware."""

import hashlib
import hmac
from time import time

from fastapi import HTTPException
from redis.exceptions import RedisError
from starlette.requests import Request

from app.core.config import settings
from app.core.rate_limit import RATE_LIMIT_SCRIPT
from app.schemas.auth import LoginRequest

MAX_MEMORY_IDENTIFIERS = 4096


def account_identifier(email: str) -> str:
    return hmac.new(
        settings.jwt_secret_key.encode(),
        b"login-account:v1:" + email.casefold().encode(),
        hashlib.sha256,
    ).hexdigest()


async def enforce_login_account_limit(payload: LoginRequest, request: Request) -> None:
    identity = account_identifier(str(payload.email))
    window = int(time() // 60)
    limit = settings.login_account_rate_limit_per_minute
    if settings.rate_limit_backend == "redis":
        try:
            count = int(
                await request.app.state.redis.eval(
                    RATE_LIMIT_SCRIPT, 1, f"login-account:{identity}:{window}", 60, limit
                )
            )
        except (RedisError, AttributeError):
            raise HTTPException(
                503, "Rate-limit service unavailable", headers={"Retry-After": "1"}
            ) from None
    else:
        buckets = getattr(request.app.state, "login_account_buckets", None)
        if buckets is None:
            buckets = request.app.state.login_account_buckets = {}
        previous_window, count = buckets.get(identity, (window, 0))
        if previous_window != window:
            count = 0
        if identity not in buckets and len(buckets) >= MAX_MEMORY_IDENTIFIERS:
            for expired in [key for key, (period, _) in buckets.items() if period != window]:
                del buckets[expired]
            if len(buckets) >= MAX_MEMORY_IDENTIFIERS:
                raise HTTPException(
                    503, "Rate-limit service unavailable", headers={"Retry-After": "1"}
                )
        count = min(count + 1, limit + 1)
        buckets[identity] = window, count
    if count > limit:
        raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": "60"})
