from uuid import UUID

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: UUID | None = None
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")


class ChatResponse(BaseModel):
    session_id: UUID
    answer: str
    review: str
    tool_results: dict
