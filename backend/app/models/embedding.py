from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator, UserDefinedType

from app.core.database import Base


EMBEDDING_DIMENSIONS = 1536


class PgVector(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_: object) -> str:
        return f"vector({self.dimensions})"


class EmbeddingVector(TypeDecorator[list[float]]):
    impl = JSON
    cache_ok = True

    def __init__(self, dimensions: int = EMBEDDING_DIMENSIONS) -> None:
        super().__init__()
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PgVector(self.dimensions))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: list[float] | None, dialect: Any) -> list[float] | str | None:
        if value is None:
            return None
        vector = [float(item) for item in value]
        if dialect.name == "postgresql":
            return "[" + ",".join(f"{item:.8g}" for item in vector) + "]"
        return vector

    def process_result_value(self, value: object, dialect: Any) -> list[float] | None:
        if value is None:
            return None
        if isinstance(value, list):
            return [float(item) for item in value]
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("[") and raw.endswith("]"):
                raw = raw[1:-1]
            if not raw:
                return []
            return [float(item) for item in raw.split(",")]
        return list(value)  # type: ignore[arg-type]


class Embedding(Base):
    __tablename__ = "embeddings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_type: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[UUID | None]
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    chunk_text: Mapped[str] = mapped_column(Text)
    chunk_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[list[float]] = mapped_column(EmbeddingVector(EMBEDDING_DIMENSIONS))
    embedding_model: Mapped[str] = mapped_column(String(120))
    embedding_dimensions: Mapped[int] = mapped_column(Integer, default=EMBEDDING_DIMENSIONS)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        postgresql.JSONB().with_variant(JSON(), "sqlite"),
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
