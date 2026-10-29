"""Regression tests for resilient RAG retrieval behavior."""

from uuid import uuid4

import pytest
from openai import OpenAIError

from app.services.rag import RagService


def test_zero_cosine_similarity_ranks_above_negative_similarity(monkeypatch):
    """Zero is a real score, not a missing-score sentinel (SQLite/pgvector parity)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    import app.models  # noqa: F401
    from app.core.config import settings
    from app.core.database import Base
    from app.models.embedding import Embedding
    from app.models.user import User
    from app.services.rag import LOCAL_EMBEDDING_MODEL

    monkeypatch.setattr(settings, "embedding_backend", "local")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    owner = uuid4()
    try:
        with Session(engine) as db:
            db.add(
                User(
                    id=owner,
                    email="score@example.invalid",
                    full_name="Synthetic",
                    password_hash="unused",
                )
            )
            db.flush()
            for name, vector in (("negative", [-1.0, 1.0]), ("zero", [0.0, 1.0])):
                db.add(
                    Embedding(
                        user_id=owner,
                        source_type="synthetic",
                        chunk_text=name,
                        chunk_hash=name,
                        embedding=vector + [0.0] * 1534,
                        embedding_model=LOCAL_EMBEDDING_MODEL,
                        embedding_dimensions=1536,
                        metadata_json={"source": {"id": name}},
                    )
                )
            db.commit()
            rag = RagService(db)
            monkeypatch.setattr(rag, "embed_text", lambda _: [1.0] + [0.0] * 1535)
            assert [row.text for row in rag.retrieve_chunks(owner, "synthetic", 2)] == [
                "zero",
                "negative",
            ]
    finally:
        engine.dispose()


def test_retrieve_chunks_degrades_when_embedding_provider_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = object.__new__(RagService)
    service.db = object()

    def fail_embedding(_: str) -> list[float]:
        raise OpenAIError("embedding quota unavailable")

    monkeypatch.setattr(service, "embed_text", fail_embedding)

    assert service.retrieve_chunks(uuid4(), "summarize the highest-risk alert") == []
