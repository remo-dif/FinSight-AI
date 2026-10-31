import os
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_KEY", "abcdefghijklmnopqrstuvwxyz1234567890")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "zyxwvutsrqponmlkjihgfedcba123456")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-1234567890")
os.environ.setdefault("EMBEDDING_BACKEND", "local")

from app.core.database import Base
from app.models.embedding import Embedding
from app.models.finance import UploadedFile
from app.models.user import User
from app.services.document_qa import DocumentQAService
from app.services.rag import RagService


@pytest.fixture
def qa_db(monkeypatch):
    monkeypatch.setattr("app.services.llm.create_openai_client", lambda: None)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
        db.rollback()


def test_authorized_document_qa_uses_only_user_documents(monkeypatch, qa_db):
    user_a = User(id=uuid4(), email="a@example.invalid", full_name="User A", password_hash="unused")
    user_b = User(id=uuid4(), email="b@example.invalid", full_name="User B", password_hash="unused")
    file_a = UploadedFile(
        id=uuid4(),
        user_id=user_a.id,
        filename="statement.pdf",
        content_type="application/pdf",
        storage_path="/tmp/a.pdf",
        status="indexed",
    )
    file_b = UploadedFile(
        id=uuid4(),
        user_id=user_b.id,
        filename="secret.pdf",
        content_type="application/pdf",
        storage_path="/tmp/b.pdf",
        status="indexed",
    )
    qa_db.add_all([user_a, user_b, file_a, file_b])
    qa_db.flush()

    embed = RagService._local_embedding("Operating expenses were 42.50 in the 2025 Q1 statement.")
    foreign_embed = RagService._local_embedding("Secret other-user note: no shared operating expenses.")

    qa_db.add_all(
        [
            Embedding(
                user_id=user_a.id,
                source_type="upload",
                source_id=file_a.id,
                chunk_index=0,
                chunk_text="Operating expenses were 42.50 in the 2025 Q1 statement.",
                chunk_hash="a",
                embedding=embed,
                embedding_model="deterministic-local-hash-v2",
                embedding_dimensions=len(embed),
                metadata_json={
                    "source": {"type": "upload", "id": str(file_a.id)},
                    "chunk": {"index": 0, "token_count": 11},
                },
            ),
            Embedding(
                user_id=user_b.id,
                source_type="upload",
                source_id=file_b.id,
                chunk_index=0,
                chunk_text="Secret other-user note: no shared operating expenses.",
                chunk_hash="b",
                embedding=foreign_embed,
                embedding_model="deterministic-local-hash-v2",
                embedding_dimensions=len(foreign_embed),
                metadata_json={
                    "source": {"type": "upload", "id": str(file_b.id)},
                    "chunk": {"index": 0, "token_count": 9},
                },
            ),
        ]
    )
    qa_db.commit()

    service = DocumentQAService(qa_db, user_a.id)
    result = service.answer("What does the statement say about operating expenses?", document_ids=[file_a.id])
    assert result["grounded"] is False
    assert result["status"] == "provider_error"
    assert result["citations"]
    assert str(result["citations"][0]["document_id"]) == str(file_a.id)
    assert "Extractive preview" in result["answer"]

    with pytest.raises(HTTPException) as exc:
        service.answer("What does the statement say about operating expenses?", document_ids=[file_b.id])
    assert exc.value.status_code == 404


def test_document_qa_uses_conservative_min_score_floor_and_relevance_policy():
    assert DocumentQAService._normalize_threshold(0.0) == 0.05
    assert DocumentQAService._normalize_threshold(0.25) == 0.25
    with pytest.raises(HTTPException):
        DocumentQAService._normalize_threshold(2.0)

    score = RagService._cosine_similarity(
        RagService._local_embedding("quarterly operating expenses"),
        RagService._local_embedding("quarterly operating expenses"),
    )
    assert score > 0.9
    assert RagService.score_is_relevant(score, 0.05) is True
    assert RagService.score_is_relevant(0.04, 0.05) is False
