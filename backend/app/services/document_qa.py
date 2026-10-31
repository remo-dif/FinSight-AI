from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.finance import UploadedFile
from app.services.llm import LLMService
from app.services.rag import DEFAULT_MIN_SCORE, RagService, RetrievalProviderError

GROUNDING_NOTE = (
    "References identify retrieved chunks in documents you are authorized to access. "
    "They do not verify that every answer claim is supported by those chunks."
)
INSUFFICIENT_ANSWER = "I could not find enough relevant evidence in the authorized documents to answer that confidently."
MAX_DOCUMENT_SCOPE = 100


class DocumentQAService:
    def __init__(self, db: Session, user_id: UUID) -> None:
        self.db = db
        self.user_id = user_id
        self.rag_service = RagService(db)
        self.llm_service = LLMService()

    def answer(
        self,
        question: str,
        *,
        document_ids: list[UUID] | None = None,
        limit: int = 5,
        min_score: float | None = None,
    ) -> dict[str, Any]:
        if not question or not question.strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Question cannot be empty")
        if document_ids is not None and not document_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "At least one document ID is required")

        authorized_document_names = self._load_authorized_documents(document_ids)
        self.db.rollback()
        if not authorized_document_names:
            return self._response("insufficient_evidence", document_ids=[])
        threshold = self._normalize_threshold(min_score)
        try:
            retrieval = self.rag_service.retrieve_chunks(
                self.user_id,
                question,
                limit=limit,
                document_ids=[UUID(doc_id) for doc_id in authorized_document_names],
                min_score=threshold,
                raise_provider_errors=True,
            )
        except RetrievalProviderError:
            return self._response(
                "provider_error",
                document_ids=list(authorized_document_names),
                answer="Document Q&A is temporarily unavailable because document search failed.",
            )
        self.db.rollback()

        retrieval = [
            row
            for row in retrieval
            if row.source_type == "upload"
            and row.source_id is not None
            and str(row.source_id) in authorized_document_names
            and RagService.score_is_relevant(row.score, threshold)
        ]
        unique_retrieval: dict[str, Any] = {}
        for row in retrieval:
            reference = self._reference(row.source_id, row.chunk_index)
            if reference is not None:
                unique_retrieval.setdefault(reference, row)
        sources = self._build_sources(list(unique_retrieval.values()), authorized_document_names)
        chunks = [
            {"text": row.text, "reference": reference}
            for reference, row in unique_retrieval.items()
            if reference in sources
        ]
        if not chunks:
            return self._response(
                "insufficient_evidence",
                document_ids=list(authorized_document_names),
                sources=list(sources.values()),
            )

        synthesis = self.llm_service.synthesize_document_answer_result(question, chunks)
        result_status = synthesis["status"]
        if result_status != "ok":
            return self._response(
                result_status,
                document_ids=list(authorized_document_names),
                sources=list(sources.values()),
                answer=synthesis["answer"],
            )

        citations = list(
            {
                reference: sources[reference]
                for reference in synthesis["references"]
                if reference in sources
            }.values()
        )
        if not citations:
            return self._response(
                "abstained",
                document_ids=list(authorized_document_names),
                sources=list(sources.values()),
                answer="I could not validate references for an evidence-backed answer, so I am abstaining.",
            )

        return {
            "answer": synthesis["answer"],
            "citations": citations,
            "sources": list(sources.values()),
            "grounded": False,
            "grounding_note": GROUNDING_NOTE,
            "abstained": False,
            "status": "ok",
            "document_ids": list(authorized_document_names),
        }

    def _load_authorized_documents(self, document_ids: list[UUID] | None) -> dict[str, str]:
        query = select(UploadedFile).where(UploadedFile.user_id == self.user_id)
        if document_ids is not None:
            normalized = list(dict.fromkeys(document_ids))
            rows = self.db.execute(query.where(UploadedFile.id.in_(normalized))).scalars().all()
            matches = {str(row.id): row.filename for row in rows}
            if len(matches) != len(normalized):
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
            return {str(doc_id): matches[str(doc_id)] for doc_id in normalized}

        rows = (
            self.db.execute(
                query.order_by(UploadedFile.created_at, UploadedFile.id).limit(
                    MAX_DOCUMENT_SCOPE + 1
                )
            )
            .scalars()
            .all()
        )
        if len(rows) > MAX_DOCUMENT_SCOPE:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Select up to {MAX_DOCUMENT_SCOPE} documents for document Q&A.",
            )
        return {str(row.id): row.filename for row in rows}

    @staticmethod
    def _normalize_threshold(min_score: float | None) -> float:
        if min_score is None:
            return DEFAULT_MIN_SCORE
        if min_score < -1.0 or min_score > 1.0:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "min_score must be between -1.0 and 1.0",
            )
        return max(DEFAULT_MIN_SCORE, float(min_score))

    @staticmethod
    def _reference(source_id: UUID | None, chunk_index: int | None) -> str | None:
        if source_id is None or chunk_index is None or chunk_index < 0:
            return None
        return f"doc:{source_id}:chunk:{chunk_index}"

    @classmethod
    def _build_sources(
        cls, retrieval: list[Any], authorized_document_names: dict[str, str]
    ) -> dict[str, dict[str, Any]]:
        sources: dict[str, dict[str, Any]] = {}
        for row in retrieval:
            source_id = row.source_id
            chunk_index = row.chunk_index
            reference = cls._reference(source_id, chunk_index)
            if reference is None or str(source_id) not in authorized_document_names:
                continue
            sources.setdefault(
                reference,
                {
                    "id": reference,
                    "document_id": str(source_id),
                    "document_name": authorized_document_names[str(source_id)],
                    "chunk_id": f"{source_id}:{chunk_index}",
                    "chunk_index": chunk_index,
                    "page": None,
                    "excerpt": str(row.text or "")[:280],
                    "score": row.score,
                    "reference": reference,
                },
            )
        return sources

    @staticmethod
    def _response(
        result_status: str,
        *,
        document_ids: list[str],
        sources: list[dict[str, Any]] | None = None,
        answer: str | None = None,
    ) -> dict[str, Any]:
        abstained = result_status != "ok"
        default_answers = {
            "abstained": INSUFFICIENT_ANSWER,
            "insufficient_evidence": INSUFFICIENT_ANSWER,
            "provider_error": "Document Q&A is temporarily unavailable. Please try again later.",
            "extractive_preview": "Extractive preview: No excerpt text is available for this response.",
        }
        return {
            "answer": answer or default_answers.get(result_status, INSUFFICIENT_ANSWER),
            "citations": [],
            "sources": sources or [],
            "grounded": False,
            "grounding_note": GROUNDING_NOTE,
            "abstained": abstained,
            "status": result_status,
            "document_ids": document_ids,
        }
