"""Real PostgreSQL concurrency; each test owns an isolated schema and sessions."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, local
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.api.routes import cases
from app.core.database import Base
from app.models.audit import AuditLog
from app.models.case import InvestigationCase
from app.models.user import User
from app.schemas.cases import CaseUpdate
from tests.test_cases import create_case, create_user


@pytest.fixture
def case_pg():
    url = os.getenv("TEST_DATABASE_URL", "")
    if not url.startswith("postgresql+psycopg://"):
        pytest.skip("TEST_DATABASE_URL with PostgreSQL is required for real concurrent updates")
    schema = f"case_integrity_{uuid4().hex}"
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={"options": f"-csearch_path={schema},public"})
    try:
        Base.metadata.create_all(engine, checkfirst=False)
        with Session(engine) as db:
            user = create_user(db)
            _, case = create_case(db, user)
            identifiers = user.id, case.transaction_id
        yield engine, identifiers
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.mark.parametrize(
    "updates",
    [
        [
            {"decision": "false_positive", "reason": "Verified legitimate."},
            {"decision": "escalate", "reason": "Verified suspicious."},
        ],
        [
            {"status": "needs_evidence", "assignee": "me"},
            {"decision": "false_positive", "reason": "Verified legitimate."},
        ],
    ],
)
def test_concurrent_snapshot_updates_have_one_winner_and_matching_audit(
    case_pg, monkeypatch, updates
):
    engine, (user_id, case_id) = case_pg
    original = cases._get_case_record
    barrier = Barrier(2, timeout=10)
    seen = local()

    def read_same_snapshot(*args, **kwargs):
        record = original(*args, **kwargs)
        if not getattr(seen, "read", False):
            seen.read = True
            barrier.wait()
        return record

    monkeypatch.setattr(cases, "_get_case_record", read_same_snapshot)

    def apply(payload):
        with Session(engine, autoflush=False) as db:
            db.execute(text("SET LOCAL lock_timeout = '5s'"))
            user = db.get(User, user_id)
            try:
                result = cases.update_case(case_id, CaseUpdate(**payload), user, db)
                return 200, result.model_dump()
            except HTTPException as exc:
                db.rollback()
                return exc.status_code, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(apply, updates))
    assert sorted(code for code, _ in results) == [200, 409]
    winner = next(index for index, (code, _) in enumerate(results) if code == 200)
    with Session(engine) as db:
        record = db.get(InvestigationCase, case_id)
        events = list(db.scalars(select(AuditLog)))
        expected = updates[winner]
        if "decision" in expected:
            expected_status = {"false_positive": "resolved", "escalate": "escalated"}[
                expected["decision"]
            ]
            assert record.status == expected_status
            assert record.decision == expected["decision"]
            assert record.decision_reason == expected["reason"]
            assert record.assignee_user_id is None
            assert [event.action for event in events] == ["case.decision_recorded"]
        else:
            assert record.status == "needs_evidence"
            assert record.decision is None
            assert record.assignee_user_id == user_id
            assert sorted(event.action for event in events) == [
                "case.assigned",
                "case.status_changed",
            ]


def test_long_lived_identity_map_does_not_hide_a_committed_decision(case_pg):
    engine, (user_id, case_id) = case_pg
    with Session(engine, autoflush=False) as stale, Session(engine) as fresh:
        cached = stale.get(InvestigationCase, case_id)
        stale_user = stale.get(User, user_id)
        cases.update_case(
            case_id,
            CaseUpdate(decision="false_positive", reason="Verified legitimate."),
            fresh.get(User, user_id),
            fresh,
        )
        assert cached.status == "new"
        with pytest.raises(HTTPException) as exc:
            cases.update_case(
                case_id, CaseUpdate(status="escalated", assignee="me"), stale_user, stale
            )
        assert exc.value.status_code == 409
        assert not stale.dirty and not stale.new
        stale.rollback()
    with Session(engine) as db:
        record = db.get(InvestigationCase, case_id)
        assert record.status == "resolved"
        assert record.decision == "false_positive"
        assert record.assignee_user_id is None
        assert len(list(db.scalars(select(AuditLog)))) == 1
