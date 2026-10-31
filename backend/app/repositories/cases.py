from uuid import UUID

from sqlalchemy import Select, select, update
from sqlalchemy.orm import Session

from app.models.case import CaseNote, InvestigationCase
from app.models.finance import Transaction
from app.models.user import User

CaseRecord = tuple[InvestigationCase, Transaction, User | None]


class CaseRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_user(self, user_id: UUID, limit: int = 50, offset: int = 0) -> list[CaseRecord]:
        query: Select[tuple[InvestigationCase, Transaction, User | None]] = (
            select(InvestigationCase, Transaction, User)
            .join(Transaction, Transaction.id == InvestigationCase.transaction_id)
            .outerjoin(User, User.id == InvestigationCase.assignee_user_id)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.posted_at.desc(), Transaction.id)
            .offset(offset)
            .limit(limit)
        )
        return list(self.db.execute(query).tuples())

    def get_for_user(self, case_id: UUID, user_id: UUID) -> CaseRecord | None:
        query: Select[tuple[InvestigationCase, Transaction, User | None]] = (
            select(InvestigationCase, Transaction, User)
            .join(Transaction, Transaction.id == InvestigationCase.transaction_id)
            .outerjoin(User, User.id == InvestigationCase.assignee_user_id)
            .where(
                InvestigationCase.transaction_id == case_id,
                Transaction.user_id == user_id,
            )
        )
        return (
            self.db.execute(query.execution_options(populate_existing=True)).tuples().one_or_none()
        )

    def update_if_unchanged(self, case: InvestigationCase, user_id: UUID, changes: dict) -> bool:
        """Compare-and-set the observed state without an ORM lost-update window."""
        statement = (
            update(InvestigationCase)
            .where(
                InvestigationCase.transaction_id == case.transaction_id,
                InvestigationCase.transaction_id.in_(
                    select(Transaction.id).where(Transaction.user_id == user_id)
                ),
                InvestigationCase.status == case.status,
                InvestigationCase.decision == case.decision,
                InvestigationCase.decision_reason == case.decision_reason,
                InvestigationCase.assignee_user_id == case.assignee_user_id,
            )
            .values(**changes)
            .execution_options(synchronize_session=False)
        )
        return self.db.execute(statement).rowcount == 1

    def notes_for_user(self, case_id: UUID, user_id: UUID) -> list[tuple[CaseNote, User | None]]:
        query = (
            select(CaseNote, User)
            .join(InvestigationCase, InvestigationCase.transaction_id == CaseNote.case_id)
            .join(Transaction, Transaction.id == InvestigationCase.transaction_id)
            .outerjoin(User, User.id == CaseNote.author_id)
            .where(CaseNote.case_id == case_id, Transaction.user_id == user_id)
            .order_by(CaseNote.created_at, CaseNote.id)
        )
        return list(self.db.execute(query).tuples())
