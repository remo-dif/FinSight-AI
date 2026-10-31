import json
import os
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from openai import APITimeoutError, OpenAIError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_KEY", "abcdefghijklmnopqrstuvwxyz1234567890")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "zyxwvutsrqponmlkjihgfedcba123456")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-1234567890")

import app.models  # noqa: F401
from app.api.routes.uploads import upload_user
from app.core.config import settings
from app.core.database import Base, get_async_db, get_db
from app.core.openai_resilience import CircuitOpenError, openai_circuit
from app.core.security import get_current_user
from app.main import create_app
from app.models.embedding import EMBEDDING_DIMENSIONS, Embedding
from app.models.finance import UploadedFile
from app.models.user import User
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.document_qa import DocumentQuestionRequest, DocumentQuestionResponse
from app.services.document_qa import GROUNDING_NOTE, DocumentQAService
from app.services.llm import LLMService
from app.services.rag import LOCAL_EMBEDDING_MODEL, RagChunkResult, RagService


@pytest.fixture
def qa_db(monkeypatch):
    monkeypatch.setattr(settings, "embedding_backend", "local")
    monkeypatch.setattr("app.services.llm.create_openai_client", lambda: None)
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            yield db
    finally:
        engine.dispose()


def add_user(db: Session, email: str) -> User:
    user = User(email=email, full_name=email, password_hash="unused")
    db.add(user)
    db.flush()
    return user


def add_document(db: Session, user: User, filename: str) -> UploadedFile:
    document = UploadedFile(
        user_id=user.id,
        filename=filename,
        content_type="application/pdf",
        storage_path=f"/private/{filename}",
        status="indexed",
    )
    db.add(document)
    db.flush()
    return document


def add_chunk(
    db: Session,
    user: User,
    document: UploadedFile,
    text: str,
    *,
    index: int = 0,
    vector: list[float] | None = None,
    metadata_source_id: str | None = None,
    source_type: str = "upload",
) -> Embedding:
    vector = vector or RagService._local_embedding(text)
    row = Embedding(
        user_id=user.id,
        source_type=source_type,
        source_id=document.id,
        chunk_index=index,
        chunk_text=text,
        chunk_hash=f"{document.id}-{index}-{uuid4()}",
        embedding=vector,
        embedding_model=LOCAL_EMBEDDING_MODEL,
        embedding_dimensions=len(vector),
        metadata_json={
            "source": {"type": source_type, "id": metadata_source_id or str(document.id)},
            "chunk": {"index": index + 10_000},
        },
    )
    db.add(row)
    db.flush()
    db.commit()
    return row


def service_with_llm(db, user, llm):
    service = DocumentQAService(db, user.id)
    service.llm_service = llm
    return service


class SuccessfulLLM:
    def __init__(self, *, answer="Operating expenses were 42.50.", references=None):
        self.answer = answer
        self.references = references
        self.chunks = None

    def synthesize_document_answer_result(self, question, chunks):
        self.chunks = chunks
        refs = (
            self.references
            if self.references is not None
            else [chunk["reference"] for chunk in chunks]
        )
        return {"answer": self.answer, "status": "ok", "references": refs}


def test_authorized_own_document_and_database_identity_override_metadata(qa_db):
    owner = add_user(qa_db, "owner@example.invalid")
    other = add_user(qa_db, "other@example.invalid")
    own = add_document(qa_db, owner, "statement.pdf")
    foreign = add_document(qa_db, other, "private-secret.pdf")
    add_chunk(
        qa_db,
        owner,
        own,
        "Operating expenses were 42.50.",
        metadata_source_id=str(foreign.id),
    )
    add_chunk(qa_db, other, foreign, "SECRET_OTHER_USER_MARKER")
    llm = SuccessfulLLM()

    result = service_with_llm(qa_db, owner, llm).answer(
        "Operating expenses were 42.50.", document_ids=[own.id]
    )

    assert result["status"] == "ok"
    assert result["grounded"] is False
    assert result["abstained"] is False
    assert [citation["document_id"] for citation in result["citations"]] == [str(own.id)]
    assert result["citations"][0]["document_name"] == own.filename
    assert result["citations"][0]["reference"] == f"doc:{own.id}:chunk:0"
    assert result["citations"][0]["chunk_index"] == 0
    assert result["citations"][0]["page"] is None
    assert str(foreign.id) not in json.dumps(result)
    assert "private-secret.pdf" not in json.dumps(result)
    assert llm.chunks == [
        {"text": "Operating expenses were 42.50.", "reference": f"doc:{own.id}:chunk:0"}
    ]


def test_foreign_and_mixed_document_scopes_are_rejected_without_leaking_metadata(qa_db):
    owner = add_user(qa_db, "owner@example.invalid")
    other = add_user(qa_db, "other@example.invalid")
    own = add_document(qa_db, owner, "own.pdf")
    foreign = add_document(qa_db, other, "highly-confidential.pdf")
    service = DocumentQAService(qa_db, owner.id)

    for scope in ([foreign.id], [own.id, foreign.id], [uuid4()]):
        with pytest.raises(HTTPException) as exc:
            service.answer("Question", document_ids=scope)
        assert exc.value.status_code == 404
        assert "highly-confidential" not in str(exc.value.detail)
        assert str(foreign.id) not in str(exc.value.detail)


def test_unscoped_retrieval_is_limited_to_owned_uploaded_documents(qa_db):
    owner = add_user(qa_db, "owner@example.invalid")
    other = add_user(qa_db, "other@example.invalid")
    own = add_document(qa_db, owner, "own.pdf")
    foreign = add_document(qa_db, other, "foreign.pdf")
    phrase = "The own document states quarterly spending is 80 dollars."
    add_chunk(qa_db, owner, own, phrase)
    add_chunk(qa_db, owner, own, phrase, index=1, source_type="transaction")
    add_chunk(qa_db, other, foreign, phrase)
    llm = SuccessfulLLM()

    result = service_with_llm(qa_db, owner, llm).answer(phrase)

    assert result["status"] == "ok"
    assert result["document_ids"] == [str(own.id)]
    assert {source["document_id"] for source in result["sources"]} == {str(own.id)}
    assert all(citation["document_id"] == str(own.id) for citation in result["citations"])


@pytest.mark.asyncio
async def test_uploaded_document_picker_lists_only_current_users_metadata(qa_db):
    owner = add_user(qa_db, "picker@example.invalid")
    other = add_user(qa_db, "picker-other@example.invalid")
    own = add_document(qa_db, owner, "my-statement.pdf")
    own_second = add_document(qa_db, owner, "my-statement-second.pdf")
    add_document(qa_db, other, "foreign-private.pdf")

    class AsyncSessionAdapter:
        async def scalars(self, statement):
            return qa_db.scalars(statement)

    app = create_app()

    async def override_async_db():
        yield AsyncSessionAdapter()

    app.dependency_overrides[upload_user] = lambda: owner
    app.dependency_overrides[get_async_db] = override_async_db
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = await client.get("/api/uploads?limit=1&offset=0")
            second = await client.get("/api/uploads?limit=1&offset=1")
        assert first.status_code == second.status_code == 200
        documents = [*first.json(), *second.json()]
        assert {document["id"] for document in documents} == {
            str(own.id),
            str(own_second.id),
        }
        assert "foreign-private.pdf" not in str(documents)
        assert documents[0]["filename"] in {own.filename, own_second.filename}
        assert all("storage_path" not in document for document in documents)
    finally:
        app.dependency_overrides.clear()


def test_no_owned_or_indexed_evidence_abstains_without_calling_model(qa_db):
    owner = add_user(qa_db, "owner@example.invalid")
    service = DocumentQAService(qa_db, owner.id)
    assert service.answer("Question")["status"] == "insufficient_evidence"
    with pytest.raises(HTTPException) as exc:
        service.answer("Question", document_ids=[])
    assert exc.value.status_code == 400

    document = add_document(qa_db, owner, "empty.pdf")
    result = service.answer("Question", document_ids=[document.id])
    assert result["status"] == "insufficient_evidence"
    assert result["abstained"] is True
    assert result["citations"] == []


def test_unscoped_document_scope_has_a_bounded_document_count(qa_db):
    owner = add_user(qa_db, "large-scope@example.invalid")
    for index in range(101):
        add_document(qa_db, owner, f"statement-{index}.pdf")

    with pytest.raises(HTTPException) as exc:
        DocumentQAService(qa_db, owner.id).answer("Question")

    assert exc.value.status_code == 400
    assert "Select up to 100 documents" in exc.value.detail


def test_retrieval_provider_failure_is_not_mislabeled_as_insufficient_evidence(qa_db, monkeypatch):
    owner = add_user(qa_db, "owner@example.invalid")
    document = add_document(qa_db, owner, "document.pdf")

    def unavailable(*args, **kwargs):
        from app.services.rag import RetrievalProviderError

        raise RetrievalProviderError("private provider details")

    monkeypatch.setattr(RagService, "retrieve_chunks", unavailable)
    result = DocumentQAService(qa_db, owner.id).answer("Question", document_ids=[document.id])
    assert result["status"] == "provider_error"
    assert result["abstained"] is True
    assert result["grounded"] is False
    assert "private provider details" not in result["answer"]


def test_low_relevance_retrieval_abstains_and_below_floor_client_score_cannot_disable_gate(
    qa_db, monkeypatch
):
    owner = add_user(qa_db, "owner@example.invalid")
    document = add_document(qa_db, owner, "document.pdf")
    weak = RagChunkResult(
        text="Not relevant",
        metadata={"source": {"id": str(document.id)}},
        score=0.049,
        source_type="upload",
        source_id=document.id,
        chunk_index=0,
    )
    service = DocumentQAService(qa_db, owner.id)
    calls = {}

    def retrieve(*args, **kwargs):
        calls.update(kwargs)
        return [weak]

    monkeypatch.setattr(service.rag_service, "retrieve_chunks", retrieve)
    service.llm_service = SuccessfulLLM()
    result = service.answer("Question", document_ids=[document.id], min_score=-1.0)
    assert calls["min_score"] == 0.05
    assert result["status"] == "insufficient_evidence"
    assert result["citations"] == []


def test_score_direction_threshold_boundary_filter_before_limit_and_tie_order(qa_db, monkeypatch):
    owner = add_user(qa_db, "owner@example.invalid")
    document = add_document(qa_db, owner, "scores.pdf")
    query = [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)

    def vector(score):
        return [score, (1.0 - score * score) ** 0.5] + [0.0] * (EMBEDDING_DIMENSIONS - 2)

    add_chunk(qa_db, owner, document, "below floor", index=0, vector=vector(0.049))
    add_chunk(qa_db, owner, document, "boundary", index=1, vector=vector(0.05))
    add_chunk(qa_db, owner, document, "higher score", index=2, vector=vector(0.8))
    add_chunk(qa_db, owner, document, "tie first", index=3, vector=vector(0.8))
    service = RagService(qa_db)
    monkeypatch.setattr(service, "embed_text", lambda _: query)

    results = service.retrieve_chunks(
        owner.id, "query", limit=2, document_ids=[document.id], min_score=0.05
    )
    assert [row.text for row in results] == ["higher score", "tie first"]
    assert [row.score for row in results] == pytest.approx([0.8, 0.8])
    assert RagService.score_is_relevant(0.05, 0.05)
    assert not RagService.score_is_relevant(0.049, 0.05)
    assert not RagService.score_is_relevant(None, 0.05)


def test_retrieval_order_is_deterministic_for_equal_scores(qa_db, monkeypatch):
    owner = add_user(qa_db, "order@example.invalid")
    document = add_document(qa_db, owner, "order.pdf")
    vector = [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)
    add_chunk(qa_db, owner, document, "chunk two", index=2, vector=vector)
    add_chunk(qa_db, owner, document, "chunk zero", index=0, vector=vector)
    service = RagService(qa_db)
    monkeypatch.setattr(service, "embed_text", lambda _: vector)

    results = service.retrieve_chunks(owner.id, "query", document_ids=[document.id])

    assert [row.text for row in results] == ["chunk zero", "chunk two"]


def llm_with_response(monkeypatch, content):
    service = LLMService.__new__(LLMService)
    service._client = object()
    service.model = "test-model"
    monkeypatch.setattr(openai_circuit, "before_call", lambda: None)
    monkeypatch.setattr(openai_circuit, "record_success", lambda: None)
    monkeypatch.setattr(openai_circuit, "record_failure", lambda: None)
    monkeypatch.setattr(
        service,
        "_complete",
        lambda **kwargs: SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        ),
    )
    return service


def llm_chunks():
    return [
        {"reference": "doc:one:chunk:0", "text": "Evidence A"},
        {"reference": "doc:two:chunk:1", "text": "Evidence B"},
    ]


def test_llm_valid_response_preserves_answer_and_deduplicates_server_references(monkeypatch):
    response = json.dumps(
        {
            "answer": "The answer is supported by available excerpts.",
            "references": ["doc:one:chunk:0", "doc:one:chunk:0"],
            "abstained": False,
        }
    )
    service = llm_with_response(monkeypatch, response)
    result = service.synthesize_document_answer_result("Question", llm_chunks())

    assert result == {
        "answer": "The answer is supported by available excerpts.",
        "status": "ok",
        "references": ["doc:one:chunk:0"],
    }


@pytest.mark.parametrize(
    "references",
    [[], ["invented:source"], ["doc:one:chunk:0", "invented:source"]],
)
def test_missing_or_invented_references_cause_abstention(monkeypatch, references):
    content = json.dumps(
        {"answer": "Generated claim.", "references": references, "abstained": False}
    )
    result = llm_with_response(monkeypatch, content).synthesize_document_answer_result(
        "Question", llm_chunks()
    )
    assert result["status"] == "abstained"
    assert result["references"] == []


def test_unsupported_claim_is_not_called_grounded_without_claim_verification(monkeypatch):
    response = json.dumps(
        {
            "answer": "The evidence proves a fabricated 999.00 charge.",
            "references": ["doc:one:chunk:0"],
            "abstained": False,
        }
    )
    result = llm_with_response(monkeypatch, response).synthesize_document_answer_result(
        "Question", llm_chunks()
    )
    assert result["status"] == "ok"
    assert result["answer"].startswith("The evidence proves")
    assert result["references"] == ["doc:one:chunk:0"]
    # Syntactically valid reference mapping is not semantic claim verification.
    assert GROUNDING_NOTE.startswith("References identify retrieved chunks")


def test_model_abstention_and_invalid_or_empty_structured_responses(monkeypatch):
    abstained = json.dumps({"answer": "", "references": [], "abstained": True})
    result = llm_with_response(monkeypatch, abstained).synthesize_document_answer_result(
        "Question", llm_chunks()
    )
    assert result["status"] == "abstained"
    assert result["references"] == []

    for invalid in ("", "not-json", json.dumps({"answer": "missing fields"})):
        result = llm_with_response(monkeypatch, invalid).synthesize_document_answer_result(
            "Question", llm_chunks()
        )
        assert result["status"] == "provider_error"
        assert result["references"] == []


def test_missing_provider_and_open_circuit_return_safe_provider_errors(monkeypatch):
    unavailable = LLMService.__new__(LLMService)
    unavailable._client = None
    unavailable.model = "test-model"
    result = unavailable.synthesize_document_answer_result("Question", llm_chunks())
    assert result["status"] == "provider_error"
    assert "not configured" in result["answer"]
    assert "Evidence A" not in result["answer"]

    service = LLMService.__new__(LLMService)
    service._client = object()
    service.model = "test-model"

    def open_circuit():
        raise CircuitOpenError("secret circuit details")

    monkeypatch.setattr(openai_circuit, "before_call", open_circuit)
    result = service.synthesize_document_answer_result("Question", llm_chunks())
    assert result["status"] == "provider_error"
    assert "busy" in result["answer"]
    assert "secret circuit details" not in result["answer"]


@pytest.mark.parametrize("error_message", ["provider timeout", "provider API error"])
def test_provider_exceptions_are_distinct_from_insufficient_evidence(monkeypatch, error_message):
    service = LLMService.__new__(LLMService)
    service._client = object()
    service.model = "test-model"
    monkeypatch.setattr(openai_circuit, "before_call", lambda: None)
    monkeypatch.setattr(openai_circuit, "record_failure", lambda: None)

    def fail(**kwargs):
        if error_message == "provider timeout":
            raise APITimeoutError(request=httpx.Request("POST", "https://example.invalid"))
        raise OpenAIError("provider API error")

    monkeypatch.setattr(service, "_complete", fail)
    result = service.synthesize_document_answer_result("Question", llm_chunks())
    assert result["status"] == "provider_error"
    assert error_message not in result["answer"]


def test_service_deduplicates_citations_and_keeps_retrieved_sources_separate(qa_db):
    owner = add_user(qa_db, "citations@example.invalid")
    document = add_document(qa_db, owner, "citation.pdf")
    text = "Cited evidence."
    add_chunk(qa_db, owner, document, text, index=0)
    add_chunk(qa_db, owner, document, text, index=0)
    llm = SuccessfulLLM(references=[f"doc:{document.id}:chunk:0", f"doc:{document.id}:chunk:0"])

    result = service_with_llm(qa_db, owner, llm).answer(text, document_ids=[document.id])

    assert len(result["sources"]) == 1
    assert len(result["citations"]) == 1
    assert result["sources"][0]["reference"] == result["citations"][0]["reference"]
    assert result["grounded"] is False


def test_duplicate_chunk_reference_uses_the_same_text_for_model_and_citation(qa_db, monkeypatch):
    owner = add_user(qa_db, "duplicate-citation@example.invalid")
    document = add_document(qa_db, owner, "duplicate-citation.pdf")
    reference = f"doc:{document.id}:chunk:0"
    first = RagChunkResult(
        text="First indexed text.",
        metadata={},
        score=0.9,
        source_type="upload",
        source_id=document.id,
        chunk_index=0,
    )
    duplicate = RagChunkResult(
        text="Different duplicate text.",
        metadata={},
        score=0.8,
        source_type="upload",
        source_id=document.id,
        chunk_index=0,
    )
    service = DocumentQAService(qa_db, owner.id)
    llm = SuccessfulLLM(references=[reference])
    service.llm_service = llm
    monkeypatch.setattr(
        service.rag_service, "retrieve_chunks", lambda *args, **kwargs: [first, duplicate]
    )

    result = service.answer("Question", document_ids=[document.id])

    assert llm.chunks == [{"text": first.text, "reference": reference}]
    assert result["citations"][0]["excerpt"] == first.text
    assert duplicate.text not in json.dumps(result)


def test_database_transactions_end_before_embedding_and_language_model_calls(qa_db, monkeypatch):
    owner = add_user(qa_db, "boundaries@example.invalid")
    document = add_document(qa_db, owner, "boundary.pdf")
    question = "Evidence outside database transactions."
    add_chunk(qa_db, owner, document, question)
    service = DocumentQAService(qa_db, owner.id)
    original_embed = service.rag_service.embed_text

    def embed(value):
        assert not qa_db.in_transaction()
        return original_embed(value)

    class BoundaryLLM:
        def synthesize_document_answer_result(self, value, chunks):
            assert not qa_db.in_transaction()
            return {
                "answer": "Evidence found.",
                "status": "ok",
                "references": [chunk["reference"] for chunk in chunks],
            }

    monkeypatch.setattr(service.rag_service, "embed_text", embed)
    service.llm_service = BoundaryLLM()

    result = service.answer(question, document_ids=[document.id])

    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_dedicated_document_endpoint_and_chat_document_mode_share_response_contract(
    qa_db, monkeypatch
):
    owner = add_user(qa_db, "api@example.invalid")
    document = add_document(qa_db, owner, "api.pdf")
    payload_text = "Document states revenue is 50."
    add_chunk(qa_db, owner, document, payload_text)
    result = {
        "answer": "Revenue is 50.",
        "citations": [
            {
                "id": f"doc:{document.id}:chunk:0",
                "document_id": document.id,
                "document_name": document.filename,
                "chunk_id": f"{document.id}:0",
                "chunk_index": 0,
                "page": None,
                "excerpt": payload_text,
                "score": 1.0,
                "reference": f"doc:{document.id}:chunk:0",
            }
        ],
        "sources": [
            {
                "id": f"doc:{document.id}:chunk:0",
                "document_id": document.id,
                "document_name": document.filename,
                "chunk_id": f"{document.id}:0",
                "chunk_index": 0,
                "page": None,
                "excerpt": payload_text,
                "score": 1.0,
                "reference": f"doc:{document.id}:chunk:0",
            }
        ],
        "grounded": False,
        "abstained": False,
        "status": "ok",
        "grounding_note": GROUNDING_NOTE,
        "document_ids": [str(document.id)],
    }

    class StubQA:
        def __init__(self, db, user_id):
            pass

        def answer(self, question, **kwargs):
            return result

    monkeypatch.setattr("app.api.routes.document_qa.DocumentQAService", StubQA)
    monkeypatch.setattr("app.api.routes.chat.DocumentQAService", StubQA)
    app = create_app()

    def override_db():
        yield qa_db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            dedicated = await client.post(
                "/api/documents/ask",
                json={"question": payload_text, "document_ids": [str(document.id)]},
            )
            chat_response = await client.post(
                "/api/chat",
                json={
                    "message": payload_text,
                    "mode": "document_qa",
                    "document_ids": [str(document.id)],
                },
            )
        assert dedicated.status_code == chat_response.status_code == 200
        dedicated_body = DocumentQuestionResponse.model_validate(dedicated.json())
        chat_body = ChatResponse.model_validate(chat_response.json())
        assert dedicated_body.status == chat_body.status == "ok"
        assert dedicated_body.grounded is chat_body.grounded is False
        assert dedicated_body.citations[0].reference == chat_body.citations[0].reference
        assert dedicated_body.sources[0].reference == chat_body.sources[0].reference
        assert chat_body.grounding_note == GROUNDING_NOTE
    finally:
        app.dependency_overrides.clear()


def test_request_alias_conflicts_and_response_status_contract_are_rejected():
    with pytest.raises(ValueError, match="only one"):
        DocumentQuestionRequest(question="one", message="two")
    with pytest.raises(ValueError, match="must match"):
        DocumentQuestionRequest(question="one", document_ids=[uuid4()], document_scope=[uuid4()])
    with pytest.raises(ValueError, match="cannot be empty"):
        ChatRequest(message="Question", mode="document_qa", document_ids=[])
    with pytest.raises(ValueError, match="only one"):
        ChatRequest(message="one", question="two")

    citation = {
        "id": "doc:one:chunk:0",
        "document_id": uuid4(),
        "document_name": "doc.pdf",
        "chunk_id": "id:0",
        "chunk_index": 0,
        "excerpt": "Evidence",
        "reference": "doc:one:chunk:0",
    }
    with pytest.raises(ValueError, match="claim-level"):
        DocumentQuestionResponse(
            answer="answer",
            citations=[citation],
            grounded=True,
            abstained=False,
            status="ok",
            grounding_note=GROUNDING_NOTE,
        )
    with pytest.raises(ValueError, match="abstentions"):
        DocumentQuestionResponse(
            answer="answer",
            citations=[],
            grounded=False,
            abstained=False,
            status="provider_error",
            grounding_note=GROUNDING_NOTE,
        )
