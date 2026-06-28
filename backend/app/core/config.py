from functools import lru_cache
from ipaddress import ip_network
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


UNSAFE_SECRET_VALUES = {
    "dev-secret",
    "dev-refresh-secret",
    "change-me-in-production",
    "change-me-too",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        populate_by_name=True,
        extra="ignore",
    )

    app_env: str = Field(default="development", validation_alias="APP_ENV")
    database_url: str = Field(validation_alias="DATABASE_URL")
    jwt_secret_key: str = Field(min_length=32, validation_alias="JWT_SECRET_KEY")
    jwt_refresh_secret_key: str = Field(
        min_length=32,
        validation_alias="JWT_REFRESH_SECRET_KEY",
    )
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = Field(default=30, validation_alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_days: int = Field(default=7, validation_alias="REFRESH_TOKEN_EXPIRE_DAYS")
    openai_api_key: str = Field(min_length=10, validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o", validation_alias="OPENAI_MODEL")
    openai_embedding_model: str = Field(
        default="text-embedding-3-large",
        validation_alias="OPENAI_EMBEDDING_MODEL",
    )
    openai_timeout_seconds: float = Field(
        default=20.0,
        gt=0,
        validation_alias="OPENAI_TIMEOUT_SECONDS",
    )
    openai_max_retries: int = Field(default=2, ge=0, le=5, validation_alias="OPENAI_MAX_RETRIES")
    openai_circuit_failure_threshold: int = Field(
        default=5,
        gt=0,
        validation_alias="OPENAI_CIRCUIT_FAILURE_THRESHOLD",
    )
    openai_circuit_reset_seconds: float = Field(
        default=30.0,
        gt=0,
        validation_alias="OPENAI_CIRCUIT_RESET_SECONDS",
    )
    storage_backend: Literal["local", "s3"] = Field(
        default="local",
        validation_alias="STORAGE_BACKEND",
    )
    upload_dir: Path = Field(default=Path("/app/uploads"), validation_alias="UPLOAD_DIR")
    max_upload_mb: int = Field(default=10, gt=0, validation_alias="MAX_UPLOAD_SIZE_MB")
    s3_upload_bucket: str | None = Field(default=None, validation_alias="S3_UPLOAD_BUCKET")
    s3_upload_prefix: str = Field(default="uploads", validation_alias="S3_UPLOAD_PREFIX")
    s3_kms_key_id: str | None = Field(default=None, validation_alias="S3_KMS_KEY_ID")
    redis_url: str = Field(default="redis://redis:6379/0", validation_alias="REDIS_URL")
    rate_limit_backend: Literal["memory", "redis"] = Field(
        default="memory",
        validation_alias="RATE_LIMIT_BACKEND",
    )
    trusted_proxy_cidrs: Annotated[list[str], NoDecode] = Field(
        default=["127.0.0.1/32", "::1/128"],
        validation_alias="TRUSTED_PROXY_CIDRS",
    )
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default=["http://localhost:3000"],
        validation_alias="ALLOWED_ORIGINS",
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    rate_limit_per_minute: int = Field(default=20, gt=0, validation_alias="RATE_LIMIT_PER_MINUTE")

    @field_validator("jwt_secret_key", "jwt_refresh_secret_key", mode="before")
    @classmethod
    def validate_jwt_secret(cls, value: str) -> str:
        if value in UNSAFE_SECRET_VALUES:
            raise ValueError("JWT secrets must be set to strong production values")
        if len(value) < 32:
            raise ValueError("JWT secrets must be at least 32 characters in production")
        return value

    @field_validator("app_env")
    @classmethod
    def validate_app_env(cls, value: str) -> str:
        if value not in {"development", "staging", "production"}:
            raise ValueError("APP_ENV must be development, staging, or production")
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError("LOG_LEVEL must be CRITICAL, ERROR, WARNING, INFO, or DEBUG")
        return normalized

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("trusted_proxy_cidrs", mode="before")
    @classmethod
    def parse_trusted_proxy_cidrs(cls, value: str | list[str]) -> list[str]:
        cidrs = [item.strip() for item in value.split(",")] if isinstance(value, str) else value
        normalized = [item for item in cidrs if item]
        for cidr in normalized:
            ip_network(cidr, strict=False)
        return normalized

    @model_validator(mode="after")
    def validate_settings(self) -> "Settings":
        if self.jwt_secret_key == self.jwt_refresh_secret_key:
            raise ValueError("JWT_SECRET_KEY and JWT_REFRESH_SECRET_KEY must differ")
        if self.app_env == "production" and self.database_url.startswith("sqlite"):
            raise ValueError("DATABASE_URL must not use SQLite in production")
        if self.app_env == "production" and (
            self.jwt_secret_key in UNSAFE_SECRET_VALUES
            or self.jwt_refresh_secret_key in UNSAFE_SECRET_VALUES
        ):
            raise ValueError("JWT secrets must be set to strong production values")
        if self.app_env == "production" and (
            not self.allowed_origins or any(origin == "*" for origin in self.allowed_origins)
        ):
            raise ValueError("ALLOWED_ORIGINS must be explicit in production")
        if self.storage_backend == "s3" and not self.s3_upload_bucket:
            raise ValueError("S3_UPLOAD_BUCKET is required when STORAGE_BACKEND=s3")
        if self.app_env == "production" and self.storage_backend != "s3":
            raise ValueError("STORAGE_BACKEND must be s3 in production")
        if self.app_env == "production" and self.rate_limit_backend != "redis":
            raise ValueError("RATE_LIMIT_BACKEND must be redis in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
