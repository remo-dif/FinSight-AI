from uuid import UUID

from app.services.analytics import FinanceAnalyticsService


class FinanceToolLayer:
    def __init__(self, analytics: FinanceAnalyticsService) -> None:
        self.analytics = analytics

    def get_transactions(self, user_id: UUID) -> dict:
        rows = self.analytics.repository.list_for_user(user_id, limit=50)
        return {"transactions": [{"merchant": r.merchant, "amount": str(r.amount), "date": r.posted_at.isoformat(), "category": r.category} for r in rows]}

    def get_monthly_summary(self, user_id: UUID, month: str) -> dict:
        return self.analytics.get_monthly_summary(user_id, month).model_dump(mode="json")

    def compare_months(self, user_id: UUID, left_month: str, right_month: str) -> dict:
        return self.analytics.compare_months(user_id, left_month, right_month)

    def get_spending_by_category(self, user_id: UUID) -> dict:
        return {key: str(value) for key, value in self.analytics.repository.spending_by_category(user_id).items()}

    def detect_anomalies(self, user_id: UUID) -> dict:
        return {"anomalies": [item.model_dump(mode="json") for item in self.analytics.detect_anomalies(user_id)]}

    def generate_budget(self, user_id: UUID) -> dict:
        return {key: str(value) for key, value in self.analytics.generate_budget(user_id).items()}

    def get_top_merchants(self, user_id: UUID) -> dict:
        return {key: str(value) for key, value in self.analytics.repository.top_merchants(user_id).items()}

    def get_recurring_payments(self, user_id: UUID) -> dict:
        return {"recurring": [item.model_dump(mode="json") for item in self.analytics.get_recurring_payments(user_id)]}
