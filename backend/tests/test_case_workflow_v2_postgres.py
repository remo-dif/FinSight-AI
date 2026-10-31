"""Database-backed lifecycle races and rollback, never simulated with SQLite."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.routes import cases
from app.models.audit import AuditLog
from app.models.case import CaseFollowUp, InvestigationCase
from app.models.user import User
from app.repositories.cases import CaseRepository
from app.schemas.cases import CaseClose, CaseFollowUpCreate, CaseNoteCreate, CaseUpdate
from tests import test_case_workflow_postgres as pg_fixtures

case_pg = pg_fixtures.case_pg


def setup_outcome(engine, user_id, case_id):
    with Session(engine) as db:
        user = db.get(User, user_id)
        cases.update_case(
            case_id, CaseUpdate(decision="escalate", reason="Initial investigation"), user, db
        )
        return cases.record_case_follow_up(
            case_id,
            CaseFollowUpCreate(
                action="escalation_outcome", reason="Reviewed evidence", expected_revision=1
            ),
            user,
            db,
        )


@pytest.mark.parametrize("competing", ["close", "note", "assignment"])
def test_concurrent_closure_and_mutation_have_one_winner(case_pg, monkeypatch, competing):
    engine, (user_id, case_id) = case_pg
    outcome = setup_outcome(engine, user_id, case_id)
    original = CaseRepository.update_if_unchanged
    barrier = Barrier(2, timeout=10)

    def race(self, *args, **kwargs):
        barrier.wait()
        return original(self, *args, **kwargs)

    monkeypatch.setattr(CaseRepository, "update_if_unchanged", race)

    def apply(operation):
        with Session(engine, autoflush=False) as db:
            user = db.get(User, user_id)
            try:
                if operation == "note":
                    cases.add_case_note(case_id, CaseNoteCreate(content="New evidence"), user, db)
                elif operation == "assignment":
                    cases.update_case(case_id, CaseUpdate(assignee="me"), user, db)
                else:
                    cases.close_case(
                        case_id,
                        CaseClose(reason="Closed after review", expected_revision=outcome.revision),
                        user,
                        db,
                    )
                return 200
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(apply, ["close", competing]))
    assert sorted(result) == [200, 409]
    with Session(engine) as db:
        case = db.get(InvestigationCase, case_id)
        history = list(db.scalars(select(CaseFollowUp).order_by(CaseFollowUp.revision)))
        closed_events = list(db.scalars(select(AuditLog).where(AuditLog.action == "case.closed")))
        assert case.revision == 3
        assert case.decision == "escalate" and case.decision_reason == "Initial investigation"
        if case.status == "resolved":
            assert [row.action for row in history] == ["escalation_outcome", "close"]
            assert len(closed_events) == 1
            assert closed_events[0].metadata_json["follow_up_id"] == str(history[-1].id)
        else:
            assert len(history) == 1 and not closed_events


def test_postgres_closure_audit_failure_is_atomic(case_pg, monkeypatch):
    engine, (user_id, case_id) = case_pg
    outcome = setup_outcome(engine, user_id, case_id)

    def fail(*args, **kwargs):
        raise RuntimeError("Audit unavailable")

    monkeypatch.setattr(cases.AuditService, "record", fail)
    with Session(engine) as db, pytest.raises(RuntimeError, match="Audit unavailable"):
        cases.close_case(
            case_id,
            CaseClose(reason="Must roll back", expected_revision=outcome.revision),
            db.get(User, user_id),
            db,
        )
    with Session(engine) as db:
        assert db.get(InvestigationCase, case_id).status == "escalated"
        assert db.get(InvestigationCase, case_id).revision == 2
        assert len(list(db.scalars(select(CaseFollowUp)))) == 1
        assert not list(db.scalars(select(AuditLog).where(AuditLog.action == "case.closed")))


@pytest.mark.parametrize("action", ["escalation_outcome", "verification_outcome"])
def test_concurrent_outcomes_cannot_both_commit(case_pg, monkeypatch, action):
    engine, (user_id, case_id) = case_pg
    with Session(engine) as db:
        decision = "escalate" if action == "escalation_outcome" else "request_verification"
        cases.update_case(
            case_id, CaseUpdate(decision=decision, reason="Initial"), db.get(User, user_id), db
        )
    original = CaseRepository.update_if_unchanged
    barrier = Barrier(2, timeout=10)

    def race(self, *args, **kwargs):
        barrier.wait()
        return original(self, *args, **kwargs)

    monkeypatch.setattr(CaseRepository, "update_if_unchanged", race)

    def apply(reason):
        with Session(engine, autoflush=False) as db:
            try:
                cases.record_case_follow_up(
                    case_id,
                    CaseFollowUpCreate(action=action, reason=reason, expected_revision=1),
                    db.get(User, user_id),
                    db,
                )
                return 201
            except HTTPException as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(apply, ["First outcome", "Second outcome"]))
    assert sorted(result) == [201, 409]
    with Session(engine) as db:
        records = list(db.scalars(select(CaseFollowUp)))
        assert len(records) == 1
        assert db.get(InvestigationCase, case_id).revision == 2
        audit = list(
            db.scalars(select(AuditLog).where(AuditLog.action == "case.follow_up_recorded"))
        )
        assert len(audit) == 1 and audit[0].metadata_json["follow_up_id"] == str(records[0].id)


def test_audit_commit_failure_rolls_back_persisted_closure(case_pg, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    engine, (user_id, case_id) = case_pg
    outcome = setup_outcome(engine, user_id, case_id)

    def invalid_audit(self, *args, **kwargs):
        self.db.add(AuditLog(action=None))

    monkeypatch.setattr(cases.AuditService, "record", invalid_audit)
    with Session(engine) as db, pytest.raises(IntegrityError):
        cases.close_case(
            case_id,
            CaseClose(reason="Must roll back at commit", expected_revision=outcome.revision),
            db.get(User, user_id),
            db,
        )
    with Session(engine) as db:
        assert db.get(InvestigationCase, case_id).status == "escalated"
        assert db.get(InvestigationCase, case_id).revision == 2
        assert len(list(db.scalars(select(CaseFollowUp)))) == 1
        assert len(list(db.scalars(select(AuditLog)))) == 2


def test_additive_migration_preserves_existing_decisions(case_pg):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    engine, (user_id, case_id) = case_pg
    with Session(engine) as db:
        cases.update_case(
            case_id,
            CaseUpdate(decision="escalate", reason="Historical decision"),
            db.get(User, user_id),
            db,
        )
    migration_file = (
        Path(__file__).resolve().parents[1] / "alembic/versions/20261031_0006_case_follow_ups.py"
    )
    spec = importlib.util.spec_from_file_location("follow_up_migration", migration_file)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE case_follow_ups"))
        connection.execute(text("ALTER TABLE investigation_cases DROP COLUMN revision"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
    with Session(engine) as db:
        case = db.get(InvestigationCase, case_id)
        assert case.revision == 0
        assert (case.status, case.decision, case.decision_reason) == (
            "escalated",
            "escalate",
            "Historical decision",
        )
        assert len(list(db.scalars(select(AuditLog)))) == 1
        assert not list(db.scalars(select(CaseFollowUp)))
        cases.record_case_follow_up(
            case_id,
            CaseFollowUpCreate(
                action="escalation_outcome", reason="New review", expected_revision=0
            ),
            db.get(User, user_id),
            db,
        )
        assert len(list(db.scalars(select(CaseFollowUp)))) == 1
