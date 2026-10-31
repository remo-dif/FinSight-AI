from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class CaseStatus(StrEnum):
    NEW = "new"
    NEEDS_EVIDENCE = "needs_evidence"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


class CaseDecision(StrEnum):
    ESCALATE = "escalate"
    REQUEST_VERIFICATION = "request_verification"
    FALSE_POSITIVE = "false_positive"


class CaseUpdate(BaseModel):
    status: CaseStatus | None = None
    assignee: Literal["me", "unassigned"] | None = None
    decision: CaseDecision | None = None
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def validate_decision_reason(self) -> "CaseUpdate":
        if self.decision is not None and not self.reason:
            raise ValueError("A reason is required when recording a decision")
        if self.reason is not None and self.decision is None:
            raise ValueError("A reason can only be submitted with a decision")
        if self.decision is not None and self.status is not None:
            raise ValueError("Record a decision separately from changing status")
        return self


class CaseNoteCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Note cannot be empty")
        return value


class CaseResponse(BaseModel):
    revision: int = 0
    id: UUID
    posted_at: date
    merchant: str
    description: str
    amount: Decimal
    currency: str
    category: str
    source: str
    status: CaseStatus
    assignee_name: str | None
    assigned_to_me: bool
    decision: CaseDecision | None
    decision_reason: str | None
    updated_at: datetime | None


class CaseNoteResponse(BaseModel):
    id: UUID
    author_name: str
    content: str
    created_at: datetime


class CaseDetailResponse(CaseResponse):
    notes: list[CaseNoteResponse]
    follow_ups: list["CaseFollowUpResponse"] = Field(default_factory=list)


class CaseClose(BaseModel):
    reason: str = Field(min_length=1, max_length=4000)
    expected_revision: int = Field(ge=0)

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A non-blank reason or outcome is required")
        return value


class CaseFollowUpCreate(CaseClose):
    action: Literal["escalation_outcome", "verification_outcome"]


class CaseFollowUpResponse(BaseModel):
    model_config = {"from_attributes": True}
    id: UUID
    case_id: UUID
    actor_id: UUID
    action: Literal["escalation_outcome", "verification_outcome", "close"]
    reason: str
    previous_status: CaseStatus
    resulting_status: CaseStatus
    revision: int
    created_at: datetime
