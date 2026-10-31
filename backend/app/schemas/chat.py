from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ChatRequest(BaseModel):
    message: str | None = Field(default=None, min_length=1, max_length=4000)
    question: str | None = Field(default=None, min_length=1, max_length=4000)
    session_id: UUID | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")
    mode: Literal["finance", "document_qa"] = "finance"
    document_ids: list[UUID] | None = None
    document_scope: list[UUID] | None = None
    limit: int = Field(default=5, ge=1, le=20)
    min_score: float | None = Field(default=None, ge=-1.0, le=1.0)

    @model_validator(mode="after")
    def normalize_message(self) -> "ChatRequest":
        if self.message and self.question and self.message.strip() != self.question.strip():
            raise ValueError("Provide only one of message or question, not both")
        if not self.message and not self.question:
            raise ValueError("message or question is required")
        if not self.message:
            self.message = self.question
        return self


class ChatResponse(BaseModel):
    session_id: UUID | None = None
    answer: str
    review: str = ""
    tool_results: dict = Field(default_factory=dict)
    citations: list[dict] = Field(default_factory=list)
    grounded: bool = False
    abstained: bool = False
    status: Literal["ok", "abstained", "provider_error", "insufficient_evidence", "extractive_preview"] = "ok"
