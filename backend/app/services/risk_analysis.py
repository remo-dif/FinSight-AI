from datetime import date
from typing import Protocol
from uuid import UUID

from app.schemas.risk import RiskSignal
from app.services.risk_signals import RiskTransaction, evaluate_risk_signals

MAX_RISK_WINDOW_DAYS = 366
MAX_RISK_RECORDS = 5000


class RiskTransactionRepository(Protocol):
    def list_for_risk_analysis(
        self,
        user_id: UUID,
        start_date: date,
        end_date: date,
        limit: int,
    ) -> list[RiskTransaction]: ...


class RiskAnalysisService:
    def __init__(self, repository: RiskTransactionRepository) -> None:
        self.repository = repository

    def evaluate(
        self,
        user_id: UUID,
        start_date: date,
        end_date: date,
        max_records: int,
    ) -> list[RiskSignal]:
        if type(max_records) is not int or not 1 <= max_records <= MAX_RISK_RECORDS:
            raise ValueError(f"max_records must be between 1 and {MAX_RISK_RECORDS}")
        window_days = (end_date - start_date).days + 1
        if window_days < 1:
            raise ValueError("end_date must be on or after start_date")
        if window_days > MAX_RISK_WINDOW_DAYS:
            raise ValueError(f"Risk analysis windows cannot exceed {MAX_RISK_WINDOW_DAYS} days")

        rows = self.repository.list_for_risk_analysis(user_id, start_date, end_date, max_records)
        if len(rows) > max_records:
            raise ValueError(
                "Risk analysis record limit exceeded; narrow the date range or increase max_records"
            )
        return evaluate_risk_signals(rows)
