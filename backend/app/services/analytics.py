from collections import defaultdict
from decimal import Decimal
from statistics import mean, pstdev
from uuid import UUID

from app.repositories.transactions import TransactionRepository
from app.schemas.finance import Anomaly, MonthlySummary, RecurringPayment
from app.services.financial_evidence import comparison_report, spending_report


class FinanceAnalyticsService:
    def __init__(self, repository: TransactionRepository) -> None:
        self.repository = repository

    def get_spending_report(
        self, user_id: UUID, month: str | None = None, currency: str | None = None
    ) -> dict:
        selected, rows = self.repository.rows_for_analysis(user_id, month, currency)
        return spending_report(rows, selected, month)

    def get_monthly_summary(
        self, user_id: UUID, month: str, currency: str | None = None
    ) -> MonthlySummary:
        currency = self.repository.currency_scope(user_id, currency, (month,))
        summary = self.repository.monthly_summary(user_id, month, currency)
        return MonthlySummary(month=month, currency=currency, **summary)

    def compare_months(
        self, user_id: UUID, left_month: str, right_month: str, currency: str | None = None
    ) -> dict:
        currency = self.repository.currency_scope(user_id, currency, (left_month, right_month))
        left = self.get_monthly_summary(user_id, left_month, currency)
        right = self.get_monthly_summary(user_id, right_month, currency)
        return {
            "left": left.model_dump(),
            "right": right.model_dump(),
            "spending_delta": right.spending - left.spending,
            "cash_flow_delta": right.net_cash_flow - left.net_cash_flow,
        }

    def detect_anomalies(self, user_id: UUID, currency: str | None = None) -> list[Anomaly]:
        _, rows = self.repository.rows_for_analysis(user_id, currency=currency)
        return self.anomalies_for_rows(rows)

    @staticmethod
    def anomalies_for_rows(rows) -> list[Anomaly]:
        transactions = [row for row in rows if row.amount < 0]
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

    def get_recurring_payments(
        self, user_id: UUID, currency: str | None = None
    ) -> list[RecurringPayment]:
        _, rows = self.repository.rows_for_analysis(user_id, currency=currency)
        return self.recurring_for_rows(rows)

    @staticmethod
    def recurring_for_rows(rows) -> list[RecurringPayment]:
        by_merchant: dict[str, list[Decimal]] = defaultdict(list)
        for row in rows:
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
        return {
            category: (amount / Decimal(3)).quantize(Decimal("0.01"))
            for category, amount in spend.items()
        }

    def compare_spending(
        self, user_id: UUID, left: str, right: str, currency: str | None = None
    ) -> dict:
        selected = self.repository.currency_scope(user_id, currency, (left, right))
        return comparison_report(
            self.get_spending_report(user_id, left, selected),
            self.get_spending_report(user_id, right, selected),
        )
