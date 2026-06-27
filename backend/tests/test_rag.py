"""Regression tests for resilient RAG retrieval behavior."""

from uuid import uuid4

import pytest
from openai import OpenAIError

from app.services.rag import RagService


def test_retrieve_chunks_degrades_when_embedding_provider_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = object.__new__(RagService)
    service.db = object()

    def fail_embedding(_: str) -> list[float]:
        raise OpenAIError("embedding quota unavailable")

    monkeypatch.setattr(service, "embed_text", fail_embedding)

    assert service.retrieve_chunks(uuid4(), "summarize the highest-risk alert") == []
