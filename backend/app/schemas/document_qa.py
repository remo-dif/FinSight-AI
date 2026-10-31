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
    question: str | None = Field(default=None, max_length=4000)
    message: str | None = Field(default=None, max_length=4000)
    document_ids: list[UUID] | None = Field(default=None, max_length=100)
    document_scope: list[UUID] | None = Field(default=None, max_length=100)
    limit: int = Field(default=5, ge=1, le=20)
    min_score: float | None = Field(default=None, ge=-1.0, le=1.0)

    @model_validator(mode="after")
    def ensure_question(self) -> "DocumentQuestionRequest":
        if self.question and self.message and self.question.strip() != self.message.strip():
            raise ValueError("Provide only one of question or message, not both")
        if not self.question and not self.message:
            raise ValueError("question or message is required")
        if (
            self.document_ids is not None
            and self.document_scope is not None
            and set(self.document_ids) != set(self.document_scope)
        ):
            raise ValueError("document_ids and document_scope must match when both are provided")
        if self.document_ids == [] or self.document_scope == []:
            raise ValueError("Document scope cannot be empty")
        if not self.question:
            self.question = self.message
        return self


class DocumentQuestionResponse(BaseModel):
    answer: str
    citations: list[DocumentCitation] = Field(default_factory=list)
    sources: list[DocumentCitation] = Field(default_factory=list)
    grounded: bool = False
    abstained: bool = False
    grounding_note: str
    document_ids: list[str] = Field(default_factory=list)
    status: Literal[
        "ok", "abstained", "provider_error", "insufficient_evidence", "extractive_preview"
    ] = "ok"

    @model_validator(mode="after")
    def validate_status_contract(self) -> "DocumentQuestionResponse":
        if self.grounded:
            raise ValueError("Document Q&A does not perform claim-level grounding verification")
        if not self.answer.strip():
            raise ValueError("Document Q&A responses must include a user-safe answer")
        if self.status == "ok":
            if self.abstained or not self.citations:
                raise ValueError(
                    "ok responses require validated citations and cannot be abstentions"
                )
        elif not self.abstained or self.citations:
            raise ValueError("Non-ok responses must be abstentions without used citations")
        if self.status == "extractive_preview" and (
            not self.answer.startswith("Extractive preview:") or not self.sources
        ):
            raise ValueError("Extractive previews must be labeled and include retrieved sources")
        return self
