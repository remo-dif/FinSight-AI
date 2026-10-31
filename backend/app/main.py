import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.api.router import api_router
from app.core.ai_observability import ai_operation, request_correlation
from app.core.config import settings
from app.core.database import engine
from app.core.logging import configure_logging
from app.core.rate_limit import (
    InMemoryRateLimitMiddleware,
    RedisRateLimitMiddleware,
    get_trusted_forwarded_scheme,
)
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
        scheme = get_trusted_forwarded_scheme(request, settings.trusted_proxy_cidrs)
        if scheme is not None:
            request.scope["scheme"] = scheme
        with request_correlation(request.headers.get("x-request-id")) as request_id:
            if request.url.path in {"/api/chat", "/api/uploads"} or request.url.path.startswith(
                "/api/document"
            ):
                with ai_operation("http.ai_request") as fields:
                    response = await call_next(request)
                    fields["status_code"] = response.status_code
                    if response.status_code >= 400:
                        fields.update(outcome="error", error_category="http")
            else:
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

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/auth/"):
            # Validation input may contain passwords, refresh tokens or a whole body.
            errors = [
                {key: value for key, value in error.items() if key != "input"}
                for error in exc.errors()
            ]
            return JSONResponse(status_code=422, content=jsonable_encoder({"detail": errors}))
        return await request_validation_exception_handler(request, exc)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
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
        login_requests_per_minute=settings.login_rate_limit_per_minute,
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
        if settings.storage_backend == "s3":
            import boto3

            await asyncio.to_thread(
                boto3.client("s3").head_bucket,
                Bucket=settings.s3_upload_bucket,
            )
        else:
            settings.upload_dir.mkdir(parents=True, exist_ok=True)
            test_file = settings.upload_dir / ".readyz"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
        return {"status": "ready"}

    return app


app = create_app()
