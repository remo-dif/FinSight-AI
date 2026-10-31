from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.finance import UploadedFile
from app.services.llm import LLMService
from app.services.rag import DEFAULT_MIN_SCORE, RagService


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
        if document_ids is not None and len(document_ids) == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "At least one document ID is required")

        authorized = self._load_authorized_documents(document_ids)
        requested_ids = [UUID(doc_id) for doc_id in authorized]
        threshold = self._normalize_threshold(min_score)
        retrieval = self.rag_service.retrieve_chunks(
            self.user_id,
            question,
            limit=limit,
            document_ids=requested_ids if requested_ids else None,
            min_score=threshold,
        )
        if not retrieval:
            return {
                "answer": "I could not find enough relevant evidence in the authorized documents to answer that confidently.",
                "citations": [],
                "grounded": False,
                "abstained": True,
                "status": "insufficient_evidence",
                "document_ids": [str(item) for item in authorized],
            }

        citations = self._build_citations(retrieval, authorized)
        synthesis = self.llm_service.synthesize_document_answer_result(
            question,
            [self._to_supported_row(row) for row in retrieval],
        )
        if synthesis["status"] != "ok":
            return {
                "answer": synthesis["answer"],
                "citations": citations,
                "grounded": False,
                "abstained": True,
                "status": synthesis["status"],
                "document_ids": [str(item) for item in authorized],
            }

        return {
            "answer": synthesis["answer"],
            "citations": citations,
            "grounded": True,
            "abstained": False,
            "status": "ok",
            "document_ids": [str(item) for item in authorized],
        }

    def _load_authorized_documents(
        self, document_ids: list[UUID] | None
    ) -> dict[str, UploadedFile]:
        if document_ids is None:
            rows = self.db.execute(
                select(UploadedFile).where(UploadedFile.user_id == self.user_id)
            ).scalars().all()
            return {str(row.id): row for row in rows}

        normalized = list(dict.fromkeys(document_ids))
        rows = self.db.execute(
            select(UploadedFile).where(
                UploadedFile.user_id == self.user_id,
                UploadedFile.id.in_(normalized),
            )
        ).scalars().all()
        matches = {str(row.id): row for row in rows}
        if len(matches) != len(normalized):
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "Document not found",
            )
        return matches

    @staticmethod
    def _normalize_threshold(min_score: float | None) -> float:
        if min_score is None:
            return DEFAULT_MIN_SCORE
        if min_score < -1.0 or min_score > 1.0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "min_score must be between -1.0 and 1.0")
        return max(DEFAULT_MIN_SCORE, float(min_score))

    @staticmethod
    def _to_supported_row(row: Any) -> dict[str, Any]:
        if isinstance(row, dict):
            return row
        metadata = getattr(row, "metadata", {}) or {}
        return {"text": getattr(row, "text", ""), "metadata": metadata, "score": getattr(row, "score", None)}

    @staticmethod
    def _build_citations(
        relevant_rows: list[Any], authorized_documents: dict[str, UploadedFile]
    ) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for row in relevant_rows:
            metadata = getattr(row, "metadata", {}) or {}
            source = metadata.get("source", {}) if isinstance(metadata, dict) else {}
            source_id = source.get("id") if isinstance(source, dict) else None
            if not source_id:
                continue
            document = authorized_documents.get(str(source_id))
            if document is None:
                continue
            chunk = metadata.get("chunk", {}) if isinstance(metadata, dict) else {}
            chunk_index = chunk.get("index") if isinstance(chunk, dict) else None
            chunk_id = f"{source_id}:{chunk_index if chunk_index is not None else 'chunk'}"
            if chunk_id in seen_ids:
                continue
            seen_ids.add(chunk_id)
            snippet = str(getattr(row, "text", "") or "")
            citations.append(
                {
                    "id": chunk_id,
                    "document_id": str(source_id),
                    "document_name": document.filename,
                    "chunk_id": chunk_id,
                    "chunk_index": chunk_index,
                    "page": None,
                    "excerpt": snippet[:280],
                    "score": getattr(row, "score", None),
                    "reference": f"doc:{source_id}:{chunk_index if chunk_index is not None else 'chunk'}",
                }
            )
        return citations
