from collections import defaultdict
from decimal import Decimal
from statistics import mean, pstdev
from uuid import UUID

from app.repositories.transactions import TransactionRepository
from app.schemas.finance import Anomaly, MonthlySummary, RecurringPayment


class FinanceAnalyticsService:
    def __init__(self, repository: TransactionRepository) -> None:
        self.repository = repository

    def get_monthly_summary(self, user_id: UUID, month: str) -> MonthlySummary:
        summary = self.repository.monthly_summary(user_id, month)
        return MonthlySummary(month=month, **summary)

    def compare_months(self, user_id: UUID, left_month: str, right_month: str) -> dict:
        left = self.get_monthly_summary(user_id, left_month)
        right = self.get_monthly_summary(user_id, right_month)
        return {
            "left": left.model_dump(),
            "right": right.model_dump(),
            "spending_delta": right.spending - left.spending,
            "cash_flow_delta": right.net_cash_flow - left.net_cash_flow,
        }

    def detect_anomalies(self, user_id: UUID) -> list[Anomaly]:
        transactions = [row for row in self.repository.list_for_user(user_id, limit=1000) if row.amount < 0]
        if len(transactions) < 3:
            return []
        values = [float(abs(row.amount)) for row in transactions]
        avg = mean(values)
        stddev = pstdev(values) or 1
        anomalies: list[Anomaly] = []
        for row in transactions:
            z_score = (float(abs(row.amount)) - avg) / stddev
            if z_score >= 2:
                anomalies.append(
                    Anomaly(
                        transaction_id=row.id,
                        merchant=row.merchant,
                        amount=abs(row.amount),
                        reason=f"Amount is {z_score:.1f} standard deviations above typical spend.",
                    )
                )
        return anomalies

    def get_recurring_payments(self, user_id: UUID) -> list[RecurringPayment]:
        by_merchant: dict[str, list[Decimal]] = defaultdict(list)
        for row in self.repository.list_for_user(user_id, limit=1000):
            if row.amount < 0:
                by_merchant[row.merchant].append(abs(row.amount))
        recurring: list[RecurringPayment] = []
        for merchant, amounts in by_merchant.items():
            if len(amounts) >= 3:
                avg = sum(amounts) / len(amounts)
                variance = max(amounts) - min(amounts)
                confidence = 0.9 if variance <= Decimal("2.00") else 0.65
                recurring.append(
                    RecurringPayment(
                        merchant=merchant,
                        amount=avg,
                        cadence="monthly",
                        confidence=confidence,
                    )
                )
        return recurring

    def generate_budget(self, user_id: UUID) -> dict[str, Decimal]:
        spend = self.repository.spending_by_category(user_id)
        return {category: (amount / Decimal("3")).quantize(Decimal("0.01")) for category, amount in spend.items()}
