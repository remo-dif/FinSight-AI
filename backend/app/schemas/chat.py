from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.schemas.document_qa import DocumentCitation


class ChatRequest(BaseModel):
    message: str | None = Field(default=None, min_length=1, max_length=4000)
    question: str | None = Field(default=None, min_length=1, max_length=4000)
    session_id: UUID | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    mode: Literal["finance", "document_qa"] = "finance"
    document_ids: list[UUID] | None = Field(default=None, max_length=100)
    document_scope: list[UUID] | None = Field(default=None, max_length=100)
    limit: int = Field(default=5, ge=1, le=20)
    min_score: float | None = Field(default=None, ge=-1.0, le=1.0)

    @model_validator(mode="after")
    def normalize_message(self) -> "ChatRequest":
        if self.message and self.question and self.message.strip() != self.question.strip():
            raise ValueError("Provide only one of message or question, not both")
        if not self.message and not self.question:
            raise ValueError("message or question is required")
        if (
            self.document_ids is not None
            and self.document_scope is not None
            and set(self.document_ids) != set(self.document_scope)
        ):
            raise ValueError("document_ids and document_scope must match when both are provided")
        if self.document_ids == [] or self.document_scope == []:
            raise ValueError("Document scope cannot be empty")
        if not self.message:
            self.message = self.question
        return self


class ChatResponse(BaseModel):
    session_id: UUID | None = None
    answer: str
    review: str = ""
    tool_results: dict = Field(default_factory=dict)
    citations: list[DocumentCitation] = Field(default_factory=list)
    sources: list[DocumentCitation] = Field(default_factory=list)
    grounded: bool = False
    abstained: bool = False
    status: Literal[
        "ok", "abstained", "provider_error", "insufficient_evidence", "extractive_preview"
    ] = "ok"
    grounding_note: str | None = None

    @model_validator(mode="after")
    def validate_document_status_contract(self) -> "ChatResponse":
        if self.grounding_note is None:
            return self
        if self.grounded:
            raise ValueError("Document Q&A does not perform claim-level grounding verification")
        if not self.answer.strip():
            raise ValueError("Document Q&A responses must include a user-safe answer")
        if self.status == "ok":
            if self.abstained or not self.citations:
                raise ValueError("ok document responses require validated citations")
        elif not self.abstained or self.citations:
            raise ValueError("Non-ok document responses must be abstentions without used citations")
        if self.status == "extractive_preview" and (
            not self.answer.startswith("Extractive preview:") or not self.sources
        ):
            raise ValueError("Extractive previews must be labeled and include retrieved sources")
        return self
