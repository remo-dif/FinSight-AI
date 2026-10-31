"""Behavioral regressions for explicit case transitions and rejected-update atomicity."""

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.routes.cases import add_case_note, get_case, update_case
from app.core.database import get_db
from app.core.security import get_current_user
from app.main import create_app
from app.models.audit import AuditLog
from app.models.case import InvestigationCase
from app.schemas.cases import CaseNoteCreate, CaseUpdate
from tests import test_cases as case_fixtures

db = case_fixtures.db
create_case = case_fixtures.create_case
create_user = case_fixtures.create_user


def audit_count(db):
    return db.scalar(select(func.count()).select_from(AuditLog))


@pytest.mark.parametrize(
    ("initial", "requested", "allowed"),
    [
        ("new", "new", True),
        ("new", "needs_evidence", True),
        ("new", "escalated", True),
        ("new", "resolved", False),
        ("needs_evidence", "new", False),
        ("needs_evidence", "needs_evidence", True),
        ("needs_evidence", "escalated", True),
        ("needs_evidence", "resolved", False),
        ("escalated", "new", False),
        ("escalated", "needs_evidence", True),
        ("escalated", "escalated", True),
        ("escalated", "resolved", False),
    ],
)
def test_undecided_case_transition_policy(db, initial, requested, allowed):
    user = create_user(db)
    _, case = create_case(db, user)
    case.status = initial
    db.commit()
    case_id = case.transaction_id
    if allowed:
        response = update_case(case_id, CaseUpdate(status=requested), user, db)
        assert response.status == requested
        assert response.decision is None
        events = list(db.scalars(select(AuditLog)))
        assert len(events) == int(initial != requested)
        if events:
            assert events[0].action == "case.status_changed"
            assert events[0].metadata_json == {
                "case_id": str(case_id),
                "from": initial,
                "to": requested,
            }
    else:
        with pytest.raises(HTTPException) as exc:
            update_case(case_id, CaseUpdate(status=requested, assignee="me"), user, db)
        assert exc.value.status_code == 409
        assert not db.dirty
        assert not db.new
        db.commit()
        db.expire_all()
        persisted = db.get(InvestigationCase, case_id)
        assert persisted.status == initial
        assert persisted.assignee_user_id is None
        assert audit_count(db) == 0


@pytest.mark.parametrize(
    ("decision", "expected_status"),
    [
        ("escalate", "escalated"),
        ("request_verification", "needs_evidence"),
        ("false_positive", "resolved"),
    ],
)
@pytest.mark.parametrize("requested", ["new", "needs_evidence", "escalated", "resolved"])
def test_decision_pins_status_and_same_status_is_idempotent(
    db, decision, expected_status, requested
):
    user = create_user(db)
    _, case = create_case(db, user)
    case_id = case.transaction_id
    update_case(case_id, CaseUpdate(decision=decision, reason="Reviewed evidence."), user, db)
    before_updated_at = case.updated_at
    if requested == expected_status:
        result = update_case(case_id, CaseUpdate(status=requested), user, db)
        assert result.status == expected_status
        assert result.updated_at == before_updated_at
    else:
        with pytest.raises(HTTPException) as exc:
            update_case(case_id, CaseUpdate(status=requested, assignee="me"), user, db)
        assert exc.value.status_code == 409
        assert not db.dirty
        assert not db.new
    db.commit()
    db.expire_all()
    persisted = db.get(InvestigationCase, case_id)
    assert persisted.status == expected_status
    assert persisted.decision == decision
    assert persisted.decision_reason == "Reviewed evidence."
    assert persisted.assignee_user_id is None
    assert audit_count(db) == 1


@pytest.mark.parametrize("decision", ["escalate", "request_verification", "false_positive"])
def test_rejected_duplicate_decision_does_not_leave_assignment_or_audit_pending(db, decision):
    user = create_user(db)
    _, case = create_case(db, user)
    case_id = case.transaction_id
    original = update_case(
        case_id, CaseUpdate(decision=decision, reason="Original evidence."), user, db
    )
    with pytest.raises(HTTPException) as exc:
        update_case(
            case_id,
            CaseUpdate(decision=decision, reason="Replacement reason.", assignee="me"),
            user,
            db,
        )
    assert exc.value.status_code == 409
    assert not db.dirty
    assert not db.new
    # A caller reusing the session must not accidentally commit rejected changes.
    db.commit()
    db.expire_all()
    persisted = db.get(InvestigationCase, case_id)
    assert persisted.status == original.status
    assert persisted.assignee_user_id is None
    assert persisted.decision_reason == "Original evidence."
    assert audit_count(db) == 1


@pytest.mark.parametrize("decision", ["escalate", "request_verification", "false_positive"])
def test_decided_cases_still_allow_assignment_and_append_only_notes(db, decision):
    user = create_user(db)
    _, case = create_case(db, user)
    case_id = case.transaction_id
    original = update_case(case_id, CaseUpdate(decision=decision, reason="Reviewed."), user, db)
    assigned = update_case(case_id, CaseUpdate(assignee="me"), user, db)
    assert assigned.assigned_to_me
    # Repeating assignment must not invent a second assignment audit event.
    update_case(case_id, CaseUpdate(assignee="me"), user, db)
    add_case_note(case_id, CaseNoteCreate(content="Additional supporting evidence."), user, db)
    unassigned = update_case(case_id, CaseUpdate(assignee="unassigned"), user, db)
    detail = get_case(case_id, user, db)
    assert not unassigned.assigned_to_me
    assert detail.status == original.status
    assert detail.decision == decision
    assert detail.decision_reason == "Reviewed."
    assert [note.content for note in detail.notes] == ["Additional supporting evidence."]
    assert audit_count(db) == 4


@pytest.mark.parametrize("requested", ["new", "needs_evidence", "escalated"])
def test_legacy_resolved_without_decision_cannot_be_silently_reopened(db, requested):
    user = create_user(db)
    _, case = create_case(db, user)
    case.status = "resolved"
    db.commit()
    case_id = case.transaction_id
    with pytest.raises(HTTPException) as exc:
        update_case(case_id, CaseUpdate(status=requested), user, db)
    assert exc.value.status_code == 409
    assert not db.dirty
    assert not db.new
    assert audit_count(db) == 0


@pytest.mark.asyncio
async def test_http_rejected_update_is_atomic_and_owner_boundary_precedes_transition_rules(db):
    owner = create_user(db, "owner@example.com")
    stranger = create_user(db, "stranger@example.com")
    _, case = create_case(db, owner)
    case_id = case.transaction_id
    update_case(case_id, CaseUpdate(decision="false_positive", reason="Owner reviewed."), owner, db)
    app = create_app()

    def override_db():
        # Deliberately no rollback: validation must not dirty the session at all.
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: owner
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            rejected = await client.patch(
                f"/api/cases/{case_id}", json={"status": "new", "assignee": "me"}
            )
            assert rejected.status_code == 409
            assert not db.dirty
            assert not db.new
            malformed = await client.patch(f"/api/cases/{case_id}", json={"status": "unsupported"})
            assert malformed.status_code == 422
            app.dependency_overrides[get_current_user] = lambda: stranger
            for method, path, body in [
                ("PATCH", f"/api/cases/{case_id}", {"status": "new", "assignee": "me"}),
                ("POST", f"/api/cases/{case_id}/notes", {"content": "Forbidden note."}),
                ("GET", f"/api/cases/{case_id}", None),
            ]:
                response = await client.request(method, path, json=body)
                assert response.status_code == 404
                assert response.json() == {"detail": "Case not found"}
        db.commit()
        db.expire_all()
        persisted = db.get(InvestigationCase, case_id)
        assert persisted.status == "resolved"
        assert persisted.assignee_user_id is None
        assert persisted.decision_reason == "Owner reviewed."
        assert audit_count(db) == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("decision", ["escalate", "request_verification", "false_positive"])
def test_legacy_resolved_cannot_record_a_new_decision(db, decision):
    user = create_user(db)
    _, case = create_case(db, user)
    case.status = "resolved"
    db.commit()
    with pytest.raises(HTTPException) as exc:
        update_case(case.transaction_id, CaseUpdate(decision=decision, reason="Late."), user, db)
    assert exc.value.status_code == 409
    assert not db.dirty and not db.new
    assert audit_count(db) == 0


def test_audit_failure_rolls_back_status_and_assignment(db, monkeypatch):
    from app.services.audit import AuditService

    user = create_user(db)
    _, case = create_case(db, user)
    case_id = case.transaction_id

    def fail_audit(*args, **kwargs):
        raise RuntimeError("synthetic audit storage failure")

    monkeypatch.setattr(AuditService, "record", fail_audit)
    with pytest.raises(RuntimeError, match="synthetic audit"):
        update_case(case_id, CaseUpdate(status="escalated", assignee="me"), user, db)
    assert not db.dirty and not db.new
    db.commit()
    db.expire_all()
    persisted = db.get(InvestigationCase, case_id)
    assert persisted.status == "new"
    assert persisted.assignee_user_id is None
    assert audit_count(db) == 0
