from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

RiskSignalType = Literal[
    "duplicate_payment_candidate",
    "daily_velocity",
    "amount_deviation",
    "new_merchant",
]


class RiskSignal(BaseModel):
    signal_id: str
    rule_version: str = "1"
    signal_type: RiskSignalType
    observed_at: date
    explanation: str
    evidence: dict[str, str | int | bool | list[str]]
    transaction_ids: list[UUID] = Field(min_length=1)
    thresholds: dict[str, str | int]
    data_sufficiency: Literal["sufficient"] = "sufficient"
    risk_level: Literal["low", "medium", "high"]
    fraud_determination: Literal[False] = False
