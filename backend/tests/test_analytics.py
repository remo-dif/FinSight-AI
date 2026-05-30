from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.services.analytics import FinanceAnalyticsService


class FakeRepository:
    def __init__(self) -> None:
        self.rows = [
            SimpleNamespace(id=uuid4(), posted_at=date(2026, 5, 1), merchant="Rent", amount=Decimal("-1500.00"), category="Housing"),
            SimpleNamespace(id=uuid4(), posted_at=date(2026, 5, 2), merchant="Coffee", amount=Decimal("-5.00"), category="Dining"),
            SimpleNamespace(id=uuid4(), posted_at=date(2026, 5, 3), merchant="Payroll", amount=Decimal("4000.00"), category="Income"),
            SimpleNamespace(id=uuid4(), posted_at=date(2026, 4, 1), merchant="Rent", amount=Decimal("-1500.00"), category="Housing"),
            SimpleNamespace(id=uuid4(), posted_at=date(2026, 3, 1), merchant="Rent", amount=Decimal("-1500.00"), category="Housing"),
        ]

    def list_for_user(self, user_id, limit=200):
        return self.rows

    def monthly_summary(self, user_id, month):
        income = Decimal("0")
        spending = Decimal("0")
        for row in self.rows:
            if row.posted_at.isoformat().startswith(month):
                if row.amount > 0:
                    income += row.amount
                else:
                    spending += abs(row.amount)
        return {"income": income, "spending": spending, "net_cash_flow": income - spending}

    def spending_by_category(self, user_id, month=None):
        return {"Housing": Decimal("4500.00"), "Dining": Decimal("5.00")}


def test_monthly_summary_calculates_cash_flow():
    summary = FinanceAnalyticsService(FakeRepository()).get_monthly_summary(uuid4(), "2026-05")
    assert summary.income == Decimal("4000.00")
    assert summary.spending == Decimal("1505.00")
    assert summary.net_cash_flow == Decimal("2495.00")


def test_recurring_payments_detect_repeated_merchants():
    recurring = FinanceAnalyticsService(FakeRepository()).get_recurring_payments(uuid4())
    assert recurring[0].merchant == "Rent"
    assert recurring[0].confidence == 0.9
