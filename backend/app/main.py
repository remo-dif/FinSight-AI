from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from sqlalchemy import text

from app.api.router import api_router
from app.core.config import settings
from app.core.database import engine
from app.core.logging import configure_logging
from app.core.rate_limit import InMemoryRateLimitMiddleware, RedisRateLimitMiddleware
from app.core.redis import create_redis_client

configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_client = None
    if settings.rate_limit_backend == "redis":
        redis_client = create_redis_client(settings.redis_url)
        await redis_client.ping()
        app.state.redis = redis_client
    try:
        yield
    finally:
        if redis_client is not None:
            await redis_client.aclose()


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid4()))
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if settings.app_env == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def create_app() -> FastAPI:
    app = FastAPI(
        title="FinSight AI Fraud Operations API",
        version="0.1.0",
        docs_url="/docs" if settings.app_env != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    rate_limit_middleware = (
        RedisRateLimitMiddleware
        if settings.rate_limit_backend == "redis"
        else InMemoryRateLimitMiddleware
    )
    app.add_middleware(
        rate_limit_middleware,
        requests_per_minute=settings.rate_limit_per_minute,
        trusted_proxy_cidrs=settings.trusted_proxy_cidrs,
    )
    app.include_router(api_router)

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["system"])
    async def readiness() -> dict[str, str]:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        if settings.rate_limit_backend == "redis":
            await app.state.redis.ping()
        settings.upload_dir.mkdir(parents=True, exist_ok=True)
        test_file = settings.upload_dir / ".readyz"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        return {"status": "ready"}

    return app


app = create_app()
