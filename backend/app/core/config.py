from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


UNSAFE_SECRET_VALUES = {
    "dev-secret",
    "dev-refresh-secret",
    "change-me-in-production",
    "change-me-too",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    database_url: str = "sqlite+pysqlite:///./finance_ai.db"
    jwt_secret_key: str = Field(default="dev-secret", min_length=8)
    jwt_refresh_secret_key: str = Field(default="dev-refresh-secret", min_length=8)
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    upload_dir: Path = Path("uploads")
    max_upload_mb: int = 20
    allowed_origins: list[str] = ["http://localhost:3000"]
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"
    openai_embedding_model: str = "text-embedding-3-large"

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_allowed_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def validate_production_settings(self) -> "Settings":
        if self.app_env != "production":
            return self
        if self.database_url.startswith("sqlite"):
            raise ValueError("DATABASE_URL must not use SQLite in production")
        if (
            self.jwt_secret_key in UNSAFE_SECRET_VALUES
            or self.jwt_refresh_secret_key in UNSAFE_SECRET_VALUES
        ):
            raise ValueError("JWT secrets must be set to strong production values")
        if len(self.jwt_secret_key) < 32 or len(self.jwt_refresh_secret_key) < 32:
            raise ValueError("JWT secrets must be at least 32 characters in production")
        if not self.allowed_origins or any(origin == "*" for origin in self.allowed_origins):
            raise ValueError("ALLOWED_ORIGINS must be explicit in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
