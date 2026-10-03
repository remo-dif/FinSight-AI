from datetime import date
from decimal import Decimal

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.routes.cases import add_case_note, get_case, list_cases, update_case
from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.models.audit import AuditLog
from app.models.case import CaseNote, InvestigationCase
from app.models.finance import Transaction
from app.models.user import User
from app.repositories.transactions import TransactionRepository
from app.schemas.cases import CaseDecision, CaseNoteCreate, CaseUpdate
from app.schemas.finance import TransactionCreate
from app.core.security import hash_password
from app.main import create_app


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def create_user(db: Session, email: str = "analyst@example.com") -> User:
    user = User(email=email, full_name="Test Analyst", password_hash=hash_password("test password"))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_case(db: Session, user: User):
    transaction = Transaction(
        user_id=user.id,
        posted_at=date(2026, 6, 18),
        merchant="Wire mule cluster",
        description="High value transfer from an unfamiliar device.",
        amount=Decimal("-7400.00"),
        currency="USD",
        category="New payee",
        source="csv",
    )
    db.add(transaction)
    db.flush()
    case = InvestigationCase(transaction_id=transaction.id)
    db.add(case)
    db.commit()
    db.refresh(case)
    return transaction, case


def test_new_transactions_receive_case_state(db: Session):
    user = create_user(db)
    transactions = TransactionRepository(db).create_many(
        user.id,
        [
            TransactionCreate(
                posted_at=date(2026, 6, 18),
                merchant="Wire mule cluster",
                amount=Decimal("-7400.00"),
            )
        ],
    )

    case = db.get(InvestigationCase, transactions[0].id)
    assert case is not None
    assert case.status == "new"


def test_case_updates_are_user_scoped_and_audited(db: Session):
    user = create_user(db)
    transaction, case = create_case(db, user)

    with pytest.raises(HTTPException) as exc:
        update_case(case.transaction_id, CaseUpdate(status=None), user, db)
    assert exc.value.status_code == 422

    with pytest.raises(HTTPException) as exc:
        update_case(case.transaction_id, CaseUpdate(status="resolved"), user, db)
    assert exc.value.status_code == 409

    assigned = update_case(case.transaction_id, CaseUpdate(assignee="me"), user, db)
    assert assigned.assigned_to_me is True
    assert assigned.assignee_name == user.full_name

    changed = update_case(case.transaction_id, CaseUpdate(status="escalated"), user, db)
    assert changed.status == "escalated"

    events = list(db.scalars(select(AuditLog).where(AuditLog.user_id == user.id)))
    assert [event.action for event in events] == ["case.assigned", "case.status_changed"]
    assert events[0].metadata_json["case_id"] == str(transaction.id)


def test_decision_requires_reason_and_cannot_be_overwritten(db: Session):
    user = create_user(db)
    _, case = create_case(db, user)

    with pytest.raises(ValueError, match="A reason is required"):
        CaseUpdate(decision=CaseDecision.FALSE_POSITIVE)

    result = update_case(
        case.transaction_id,
        CaseUpdate(decision=CaseDecision.FALSE_POSITIVE, reason="Evidence disproves the signal."),
        user,
        db,
    )
    assert result.status == "resolved"
    assert result.decision == "false_positive"

    with pytest.raises(HTTPException) as exc:
        update_case(
            case.transaction_id,
            CaseUpdate(decision=CaseDecision.ESCALATE, reason="New evidence supports escalation."),
            user,
            db,
        )
    assert exc.value.status_code == 409


def test_notes_are_append_only_and_included_in_case_detail(db: Session):
    user = create_user(db)
    _, case = create_case(db, user)

    note = add_case_note(case.transaction_id, CaseNoteCreate(content="  Reviewed source statement.  "), user, db)
    detail = get_case(case.transaction_id, user, db)

    assert note.content == "Reviewed source statement."
    assert len(detail.notes) == 1
    assert detail.notes[0].author_name == user.full_name
    assert db.scalar(select(AuditLog).where(AuditLog.action == "case.note_added")) is not None
    assert db.scalar(select(CaseNote).where(CaseNote.id == note.id)) is not None


def test_user_cannot_read_or_update_another_users_case(db: Session):
    owner = create_user(db, "owner@example.com")
    other_user = create_user(db, "other@example.com")
    _, case = create_case(db, owner)

    with pytest.raises(HTTPException) as exc:
        get_case(case.transaction_id, other_user, db)
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        update_case(case.transaction_id, CaseUpdate(status="resolved"), other_user, db)
    assert exc.value.status_code == 404

    assert list_cases(limit=50, offset=0, user=other_user, db=db) == []


@pytest.mark.asyncio
async def test_case_http_workflow_validates_and_returns_persisted_state(db: Session):
    user = create_user(db)
    transaction, _ = create_case(db, user)
    app = create_app()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            listed = await client.get("/api/cases")
            changed = await client.patch(
                f"/api/cases/{transaction.id}",
                json={"status": "escalated"},
            )
            invalid_decision = await client.patch(
                f"/api/cases/{transaction.id}",
                json={"decision": "false_positive"},
            )
            note = await client.post(
                f"/api/cases/{transaction.id}/notes",
                json={"content": "Confirmed with the account holder."},
            )
            detail = await client.get(f"/api/cases/{transaction.id}")

        assert listed.status_code == 200
        assert listed.json()[0]["id"] == str(transaction.id)
        assert changed.status_code == 200
        assert changed.json()["status"] == "escalated"
        assert invalid_decision.status_code == 422
        assert note.status_code == 201
        assert detail.status_code == 200
        assert detail.json()["notes"][0]["content"] == "Confirmed with the account holder."
    finally:
        app.dependency_overrides.clear()
