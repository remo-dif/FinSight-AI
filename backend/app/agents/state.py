from typing import Any, Literal, TypedDict
from uuid import UUID


AgentIntent = Literal["anomaly", "recurring", "budget", "merchant", "category", "summary"]
ReviewStatus = Literal["accepted", "rejected"]


class AgentState(TypedDict, total=False):
    user_id: UUID
    message: str
    intent: AgentIntent
    tool_results: dict[str, Any]
    agent_outputs: dict[str, str]
    review_status: ReviewStatus
    review: str
    final_answer: str
