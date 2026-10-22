import json
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.api.routes.chat import chat
from app.core.database import Base
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User
from app.schemas.chat import ChatRequest
from app.services.rag import RagService


@pytest.fixture
def chat_db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(
            email="synthetic@example.invalid", full_name="Synthetic", password_hash="unused"
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        yield db, user
    engine.dispose()


def install_providers(monkeypatch, db, fail=False):
    calls = []

    def embedding(self, value):
        assert not db.in_transaction(), "Database transaction held across embedding call"
        calls.append("embedding")
        return [0.0] * 1536

    class LLM:
        def synthesize_financial_answer(self, message, intent, results, chunks):
            assert not db.in_transaction(), "Database transaction held across LLM call"
            calls.append("llm")
            if fail:
                raise RuntimeError("Synthetic provider failure")
            return json.dumps({"claim_ids": [f["key"] for f in results["_evidence"]["facts"]]})

    monkeypatch.setattr(RagService, "embed_text", embedding)
    monkeypatch.setattr("app.api.routes.chat.LLMService", LLM)
    return calls


def test_no_transaction_during_external_calls_and_atomic_turn(chat_db, monkeypatch):
    db, user = chat_db
    calls = install_providers(monkeypatch, db)
    response = chat(ChatRequest(message="summary 2025-01", currency="EUR"), user, db)
    assert calls == ["embedding", "llm"]
    assert "2025-01" in response.answer and "EUR" in response.answer
    assert db.scalar(select(func.count()).select_from(ChatSession)) == 1
    assert db.scalar(select(func.count()).select_from(ChatMessage)) == 2
    second = chat(
        ChatRequest(message="summary 2025-02", session_id=response.session_id, currency="EUR"),
        user,
        db,
    )
    assert second.session_id == response.session_id
    assert db.scalar(select(func.count()).select_from(ChatMessage)) == 4
    comparison = chat(ChatRequest(message="compare 2025-01 to 2025-02", currency="EUR"), user, db)
    assert comparison.tool_results["_evidence"]["period"] == "2025-01 to 2025-02"
    assert comparison.review.startswith("Accepted")


def test_provider_failure_leaves_no_partial_chat(chat_db, monkeypatch):
    db, user = chat_db
    install_providers(monkeypatch, db, fail=True)
    with pytest.raises(RuntimeError, match="Synthetic provider failure"):
        chat(ChatRequest(message="summary 2025-01"), user, db)
    assert not db.in_transaction()
    assert db.scalar(select(func.count()).select_from(ChatSession)) == 0
    assert db.scalar(select(func.count()).select_from(ChatMessage)) == 0


def test_unknown_session_is_rejected_before_providers(chat_db, monkeypatch):
    db, user = chat_db
    calls = install_providers(monkeypatch, db)
    with pytest.raises(HTTPException) as exc:
        chat(ChatRequest(message="summary", session_id=uuid4()), user, db)
    assert exc.value.status_code == 404 and calls == []


def test_foreign_session_is_rejected_before_providers(chat_db, monkeypatch):
    db, user = chat_db
    other = User(email="other@example.invalid", full_name="Other Synthetic", password_hash="unused")
    db.add(other)
    db.flush()
    foreign = ChatSession(user_id=other.id, title="Synthetic")
    db.add(foreign)
    db.commit()
    calls = install_providers(monkeypatch, db)
    with pytest.raises(HTTPException) as exc:
        chat(ChatRequest(message="summary", session_id=foreign.id), user, db)
    assert exc.value.status_code == 404 and calls == []


@pytest.mark.parametrize(
    "message",
    ["summary 2025-13", "summary EUR USD", "summary 0000-01", "compare 2025-01 2025-02 2025-03"],
)
def test_invalid_reporting_context_is_rejected(chat_db, monkeypatch, message):
    db, user = chat_db
    calls = install_providers(monkeypatch, db)
    with pytest.raises(HTTPException) as exc:
        chat(ChatRequest(message=message), user, db)
    assert exc.value.status_code == 422 and calls == []


def test_persistence_failure_rolls_back_the_whole_turn(chat_db, monkeypatch):
    from sqlalchemy import event

    from app.core.database import get_db

    db, user = chat_db
    install_providers(monkeypatch, db)
    monkeypatch.setattr("app.core.database.SessionLocal", lambda: db)
    dependency = get_db()
    assert next(dependency) is db

    def fail_commit(session):
        raise RuntimeError("Synthetic commit failure")

    event.listen(db, "before_commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="Synthetic commit failure") as exc:
            chat(ChatRequest(message="summary 2025-01", currency="EUR"), user, db)
        with pytest.raises(RuntimeError, match="Synthetic commit failure"):
            dependency.throw(exc.value)
    finally:
        event.remove(db, "before_commit", fail_commit)
        dependency.close()
    assert db.scalar(select(func.count()).select_from(ChatSession)) == 0
    assert db.scalar(select(func.count()).select_from(ChatMessage)) == 0
