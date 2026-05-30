from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import Select, case, func, select
from sqlalchemy.orm import Session

from app.models.finance import Transaction
from app.schemas.finance import TransactionCreate


class TransactionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_many(self, user_id: UUID, items: list[TransactionCreate]) -> list[Transaction]:
        rows = [Transaction(user_id=user_id, **item.model_dump()) for item in items]
        self.db.add_all(rows)
        self.db.flush()
        for row in rows:
            self.db.refresh(row)
        return rows

    def list_for_user(
        self,
        user_id: UUID,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 200,
    ) -> list[Transaction]:
        query: Select[tuple[Transaction]] = select(Transaction).where(Transaction.user_id == user_id)
        if start_date:
            query = query.where(Transaction.posted_at >= start_date)
        if end_date:
            query = query.where(Transaction.posted_at <= end_date)
        query = query.order_by(Transaction.posted_at.desc()).limit(limit)
        return list(self.db.scalars(query))

    def monthly_summary(self, user_id: UUID, month: str) -> dict[str, Decimal]:
        start_date, end_date = self._month_range(month)
        income_expr = case((Transaction.amount > 0, Transaction.amount), else_=0)
        spending_expr = case((Transaction.amount < 0, -Transaction.amount), else_=0)
        income, spending = self.db.execute(
            select(func.coalesce(func.sum(income_expr), 0), func.coalesce(func.sum(spending_expr), 0))
            .where(Transaction.user_id == user_id)
            .where(Transaction.posted_at >= start_date, Transaction.posted_at < end_date)
        ).one()
        return {"income": income, "spending": spending, "net_cash_flow": income - spending}

    def spending_by_category(self, user_id: UUID, month: str | None = None) -> dict[str, Decimal]:
        query = select(Transaction.category, func.sum(Transaction.amount)).where(
            Transaction.user_id == user_id,
            Transaction.amount < 0,
        )
        if month:
            start_date, end_date = self._month_range(month)
            query = query.where(Transaction.posted_at >= start_date, Transaction.posted_at < end_date)
        query = query.group_by(Transaction.category)
        return {category: abs(total or Decimal("0")) for category, total in self.db.execute(query)}

    def top_merchants(self, user_id: UUID, limit: int = 10) -> dict[str, Decimal]:
        rows = self.db.execute(
            select(Transaction.merchant, func.sum(-Transaction.amount).label("total"))
            .where(Transaction.user_id == user_id, Transaction.amount < 0)
            .group_by(Transaction.merchant)
            .order_by(func.sum(-Transaction.amount).desc())
            .limit(limit)
        )
        return {merchant: total or Decimal("0") for merchant, total in rows}

    @staticmethod
    def _month_range(month: str) -> tuple[date, date]:
        start = date.fromisoformat(f"{month}-01")
        if start.month == 12:
            end = date(start.year + 1, 1, 1)
        else:
            end = date(start.year, start.month + 1, 1)
        return start, end
