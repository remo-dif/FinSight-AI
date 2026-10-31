from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class DocumentCitation(BaseModel):
    id: str
    document_id: UUID
    document_name: str
    chunk_id: str
    chunk_index: int | None = None
    page: int | None = None
    excerpt: str
    score: float | None = None
    reference: str


class DocumentQuestionRequest(BaseModel):
    question: str | None = None
    message: str | None = None
    document_ids: list[UUID] | None = None
    document_scope: list[UUID] | None = None
    limit: int = Field(default=5, ge=1, le=20)
    min_score: float | None = Field(default=None, ge=-1.0, le=1.0)

    @model_validator(mode="after")
    def ensure_question(self) -> "DocumentQuestionRequest":
        if self.question and self.message and self.question.strip() != self.message.strip():
            raise ValueError("Provide only one of question or message, not both")
        if not self.question and not self.message:
            raise ValueError("question or message is required")
        if not self.question:
            self.question = self.message
        return self


class DocumentQuestionResponse(BaseModel):
    answer: str
    citations: list[DocumentCitation] = Field(default_factory=list)
    grounded: bool = False
    abstained: bool = False
    document_ids: list[str] = Field(default_factory=list)
    status: Literal["ok", "abstained", "provider_error", "insufficient_evidence", "extractive_preview"] = "ok"

    @model_validator(mode="after")
    def sync_status(self) -> "DocumentQuestionResponse":
        if self.status in {"ok", "abstained"}:
            if self.abstained:
                self.status = "abstained"
            else:
                self.status = "ok"
        return self
