import hashlib
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.embedding import EMBEDDING_DIMENSIONS, Embedding


LOCAL_EMBEDDING_MODEL = "deterministic-local-hash-v1"
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._%+-]*")


@dataclass(frozen=True)
class TextChunk:
    index: int
    text: str
    start_char: int
    end_char: int


@dataclass(frozen=True)
class RagChunkResult:
    text: str
    metadata: dict[str, Any]
    score: float | None = None


class RagService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self._openai_client = OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    def chunk_text(self, text: str, max_chars: int = 1200, overlap_chars: int = 160) -> list[str]:
        return [chunk.text for chunk in self._chunk_text(text, max_chars, overlap_chars)]

    def index_text(
        self,
        user_id: UUID,
        source_type: str,
        source_id: UUID | None,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        chunks = self._chunk_text(text)
        if not chunks:
            return 0

        embeddings = self.embed_texts([chunk.text for chunk in chunks])
        records = []
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            records.append(
                Embedding(
                    user_id=user_id,
                    source_type=source_type,
                    source_id=source_id,
                    chunk_index=chunk.index,
                    chunk_text=chunk.text,
                    chunk_hash=self._chunk_hash(chunk.text),
                    embedding=embedding,
                    embedding_model=self.embedding_model,
                    embedding_dimensions=len(embedding),
                    metadata_json=self._build_metadata(source_type, source_id, chunk, metadata),
                )
            )
        self.db.add_all(records)
        self.db.flush()
        return len(chunks)

    def retrieve(self, user_id: UUID, query: str, limit: int = 5) -> list[str]:
        return [row.text for row in self.retrieve_chunks(user_id, query, limit)]

    def retrieve_chunks(self, user_id: UUID, query: str, limit: int = 5) -> list[RagChunkResult]:
        if limit <= 0 or not query.strip():
            return []

        query_embedding = self.embed_text(query)
        bind = self.db.get_bind()
        if bind.dialect.name == "postgresql":
            rows = self.db.execute(
                text(
                    """
                    SELECT chunk_text, metadata_json, 1 - (embedding <=> CAST(:embedding AS vector)) AS score
                    FROM embeddings
                    WHERE user_id = :user_id
                    ORDER BY embedding <=> CAST(:embedding AS vector)
                    LIMIT :limit
                    """
                ),
                {
                    "user_id": str(user_id),
                    "embedding": self._format_pgvector(query_embedding),
                    "limit": limit,
                },
            ).mappings()
            return [
                RagChunkResult(
                    text=str(row["chunk_text"]),
                    metadata=dict(row["metadata_json"] or {}),
                    score=float(row["score"]) if row["score"] is not None else None,
                )
                for row in rows
            ]

        rows = self.db.query(Embedding).filter(Embedding.user_id == user_id).all()
        ranked = sorted(
            (
                RagChunkResult(
                    text=row.chunk_text,
                    metadata=row.metadata_json or {},
                    score=self._cosine_similarity(query_embedding, row.embedding or []),
                )
                for row in rows
            ),
            key=lambda item: item.score or -1.0,
            reverse=True,
        )
        return ranked[:limit]

    @property
    def embedding_model(self) -> str:
        if self._openai_client:
            return settings.openai_embedding_model
        return LOCAL_EMBEDDING_MODEL

    def embed_text(self, value: str) -> list[float]:
        return self.embed_texts([value])[0]

    def embed_texts(self, values: list[str]) -> list[list[float]]:
        if not values:
            return []
        if self._openai_client:
            kwargs: dict[str, Any] = {
                "model": settings.openai_embedding_model,
                "input": values,
            }
            if settings.openai_embedding_model.startswith("text-embedding-3"):
                kwargs["dimensions"] = EMBEDDING_DIMENSIONS
            response = self._openai_client.embeddings.create(**kwargs)
            return [[float(item) for item in row.embedding] for row in response.data]
        return [self._local_embedding(value) for value in values]

    def _chunk_text(
        self,
        text: str,
        max_chars: int = 1200,
        overlap_chars: int = 160,
    ) -> list[TextChunk]:
        if max_chars < 200:
            raise ValueError("max_chars must be at least 200")
        overlap_chars = min(max(overlap_chars, 0), max_chars // 3)
        normalized = self._normalize_text(text)
        if not normalized:
            return []

        chunks: list[TextChunk] = []
        position = 0
        text_length = len(normalized)
        while position < text_length:
            start = self._skip_leading_whitespace(normalized, position)
            if start >= text_length:
                break
            hard_end = min(start + max_chars, text_length)
            end = self._choose_chunk_end(normalized, start, hard_end)
            chunk_text = normalized[start:end].strip()
            if chunk_text:
                chunks.append(TextChunk(len(chunks), chunk_text, start, end))
            if end >= text_length:
                break
            next_position = max(end - overlap_chars, start + 1)
            position = self._skip_leading_whitespace(normalized, next_position)
        return chunks

    def _choose_chunk_end(self, value: str, start: int, hard_end: int) -> int:
        if hard_end >= len(value):
            return len(value)
        minimum = start + max(120, (hard_end - start) // 2)
        candidates = [
            value.rfind("\n\n", minimum, hard_end),
            value.rfind("\n", minimum, hard_end),
            max(value.rfind(". ", minimum, hard_end), value.rfind("? ", minimum, hard_end), value.rfind("! ", minimum, hard_end)),
            value.rfind(" ", minimum, hard_end),
        ]
        split_at = max(candidates)
        if split_at <= start:
            return hard_end
        if value[split_at : split_at + 2] in {". ", "? ", "! "}:
            return split_at + 1
        return split_at

    def _normalize_text(self, value: str) -> str:
        normalized = value.replace("\r\n", "\n").replace("\r", "\n")
        normalized = _CONTROL_CHARS.sub(" ", normalized)
        normalized = re.sub(r"[ \t]+", " ", normalized)
        normalized = re.sub(r"\n{3,}", "\n\n", normalized)
        return normalized.strip()

    def _skip_leading_whitespace(self, value: str, position: int) -> int:
        while position < len(value) and value[position].isspace():
            position += 1
        return position

    def _local_embedding(self, value: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIMENSIONS
        tokens = _TOKEN_RE.findall(value.lower())
        if not tokens:
            tokens = [hashlib.sha256(value.encode("utf-8")).hexdigest()]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
            sign = 1.0 if digest[4] & 1 else -1.0
            weight = 1.0 + digest[5] / 255.0
            vector[index] += sign * weight
        norm = math.sqrt(sum(item * item for item in vector))
        if norm == 0:
            return vector
        return [item / norm for item in vector]

    def _build_metadata(
        self,
        source_type: str,
        source_id: UUID | None,
        chunk: TextChunk,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "source": {
                "type": source_type,
                "id": str(source_id) if source_id else None,
            },
            "chunk": {
                "index": chunk.index,
                "start_char": chunk.start_char,
                "end_char": chunk.end_char,
                "char_count": len(chunk.text),
                "hash": self._chunk_hash(chunk.text),
            },
            "custom": self._json_safe(metadata or {}),
        }

    def _json_safe(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): self._json_safe(item) for key, item in value.items()}
        if isinstance(value, list | tuple | set):
            return [self._json_safe(item) for item in value]
        if isinstance(value, UUID | datetime | date | Decimal | Path):
            return str(value)
        if isinstance(value, str | int | float | bool) or value is None:
            return value
        return str(value)

    def _chunk_hash(self, value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _format_pgvector(self, value: list[float]) -> str:
        return "[" + ",".join(f"{item:.8g}" for item in value) + "]"

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return -1.0
        numerator = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if left_norm == 0 or right_norm == 0:
            return -1.0
        return numerator / (left_norm * right_norm)
