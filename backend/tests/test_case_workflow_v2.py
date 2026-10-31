"""Lifecycle requirements; real PostgreSQL tests live in a separate module."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.api.routes import cases
from app.models.audit import AuditLog
from app.models.case import CaseFollowUp
from app.schemas.cases import CaseClose, CaseFollowUpCreate, CaseNoteCreate, CaseUpdate
from tests import test_cases as case_fixtures
from tests.test_cases import create_case, create_user

db = case_fixtures.db


def prepared(db, decision="escalate"):
    user = create_user(db)
    _, case = create_case(db, user)
    cases.update_case(
        case.transaction_id, CaseUpdate(decision=decision, reason="Initial evidence"), user, db
    )
    return user, case.transaction_id


@pytest.mark.parametrize(
    "decision,action",
    [("escalate", "escalation_outcome"), ("request_verification", "verification_outcome")],
)
def test_follow_up_then_explicit_close_preserves_initial_decision(db, decision, action):
    user, case_id = prepared(db, decision)
    detail = cases.get_case(case_id, user, db)
    outcome = cases.record_case_follow_up(
        case_id,
        CaseFollowUpCreate(
            action=action, reason="Reviewed additional evidence", expected_revision=detail.revision
        ),
        user,
        db,
    )
    assert outcome.id != case_id
    assert outcome.actor_id == user.id
    assert outcome.previous_status == outcome.resulting_status == detail.status
    closed = cases.close_case(
        case_id,
        CaseClose(reason="Investigation complete", expected_revision=outcome.revision),
        user,
        db,
    )
    assert closed.status == "resolved"
    assert closed.decision == decision and closed.decision_reason == "Initial evidence"
    history = cases.list_case_follow_ups(case_id, user, db)
    assert [item.action for item in history] == [action, "close"]
    assert [item.revision for item in history] == sorted(item.revision for item in history)
    for operation in [
        lambda: cases.close_case(
            case_id, CaseClose(reason="Duplicate", expected_revision=closed.revision), user, db
        ),
        lambda: cases.update_case(case_id, CaseUpdate(assignee="me"), user, db),
        lambda: cases.add_case_note(case_id, CaseNoteCreate(content="Late note"), user, db),
        lambda: cases.record_case_follow_up(
            case_id,
            CaseFollowUpCreate(action=action, reason="Replace", expected_revision=closed.revision),
            user,
            db,
        ),
    ]:
        with pytest.raises(HTTPException) as exc:
            operation()
        assert exc.value.status_code == 409
    assert len(cases.list_case_follow_ups(case_id, user, db)) == 2


def test_closure_requires_outcome_and_cannot_replace_it(db):
    user, case_id = prepared(db)
    with pytest.raises(HTTPException) as exc:
        cases.close_case(case_id, CaseClose(reason="Too soon", expected_revision=1), user, db)
    assert exc.value.status_code == 409
    outcome = cases.record_case_follow_up(
        case_id,
        CaseFollowUpCreate(action="escalation_outcome", reason="Outcome", expected_revision=1),
        user,
        db,
    )
    for action, revision in [
        ("verification_outcome", outcome.revision),
        ("escalation_outcome", outcome.revision),
        ("escalation_outcome", 1),
    ]:
        with pytest.raises(HTTPException) as exc:
            cases.record_case_follow_up(
                case_id,
                CaseFollowUpCreate(
                    action=action, reason="Not permitted", expected_revision=revision
                ),
                user,
                db,
            )
        assert exc.value.status_code == 409
    assert len(cases.list_case_follow_ups(case_id, user, db)) == 1


@pytest.mark.parametrize("reason", ["", "   ", "\n\t"])
def test_reason_required(reason):
    with pytest.raises(ValidationError):
        CaseClose(reason=reason, expected_revision=0)
    with pytest.raises(ValidationError):
        CaseFollowUpCreate(action="escalation_outcome", reason=reason, expected_revision=0)


def test_foreign_user_cannot_read_follow_up_or_close(db):
    _user, case_id = prepared(db)
    stranger = create_user(db, "stranger-v2@example.test")
    for operation in [
        lambda: cases.list_case_follow_ups(case_id, stranger, db),
        lambda: cases.record_case_follow_up(
            case_id,
            CaseFollowUpCreate(action="escalation_outcome", reason="Attempt", expected_revision=1),
            stranger,
            db,
        ),
        lambda: cases.close_case(
            case_id, CaseClose(reason="Attempt", expected_revision=1), stranger, db
        ),
    ]:
        with pytest.raises(HTTPException) as exc:
            operation()
        assert exc.value.status_code == 404
    assert not list(db.scalars(select(CaseFollowUp)))


def test_audit_failure_rolls_back_follow_up_and_revision(db, monkeypatch):
    user, case_id = prepared(db)
    before = len(list(db.scalars(select(AuditLog))))

    def fail(*args, **kwargs):
        raise RuntimeError("Audit unavailable")

    monkeypatch.setattr(cases.AuditService, "record", fail)
    with pytest.raises(RuntimeError, match="Audit unavailable"):
        cases.record_case_follow_up(
            case_id,
            CaseFollowUpCreate(action="escalation_outcome", reason="Outcome", expected_revision=1),
            user,
            db,
        )
    assert not list(db.scalars(select(CaseFollowUp)))
    assert cases.get_case(case_id, user, db).revision == 1
    assert len(list(db.scalars(select(AuditLog)))) == before


def test_false_positive_remains_resolved_without_follow_up(db):
    user, case_id = prepared(db, "false_positive")
    assert cases.get_case(case_id, user, db).status == "resolved"
    with pytest.raises(HTTPException) as exc:
        cases.record_case_follow_up(
            case_id,
            CaseFollowUpCreate(
                action="escalation_outcome", reason="Not required", expected_revision=1
            ),
            user,
            db,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_lifecycle_http_validation_and_authentication(db):
    import httpx

    from app.core.database import get_db
    from app.core.security import get_current_user
    from app.main import create_app

    user, case_id = prepared(db, "request_verification")
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            path = f"/api/cases/{case_id}"
            for payload in [
                {"action": "close", "reason": "Bypass", "expected_revision": 1},
                {"action": "verification_outcome", "reason": " ", "expected_revision": 1},
                {"action": "verification_outcome", "reason": "Result"},
                {"action": "verification_outcome", "reason": "Result", "expected_revision": -1},
            ]:
                assert (await client.post(path + "/follow-ups", json=payload)).status_code == 422
            response = await client.post(
                path + "/follow-ups",
                json={
                    "action": "verification_outcome",
                    "reason": "Verified by new evidence",
                    "expected_revision": 1,
                },
            )
            assert response.status_code == 201
            assert (
                await client.post(
                    path + "/close", json={"reason": "Stale view", "expected_revision": 1}
                )
            ).status_code == 409
            response = await client.post(
                path + "/close", json={"reason": "Reviewed and complete", "expected_revision": 2}
            )
            assert response.status_code == 200 and response.json()["status"] == "resolved"
            detail = (await client.get(path)).json()
            history = (await client.get(path + "/follow-ups")).json()
            assert detail["follow_ups"] == history and len(history) == 2
            app.dependency_overrides.pop(get_current_user)
            assert (await client.get(path + "/follow-ups")).status_code == 401
            assert (
                await client.post(
                    path + "/close", json={"reason": "Unauthorized", "expected_revision": 3}
                )
            ).status_code == 401
    finally:
        app.dependency_overrides.clear()
