"""Conservative transitions; reopening/redecision require a separate business operation."""

from fastapi import HTTPException, status

from app.models.case import InvestigationCase
from app.schemas.cases import CaseDecision, CaseStatus, CaseUpdate

DECISION_STATUSES = {
    CaseDecision.ESCALATE: CaseStatus.ESCALATED,
    CaseDecision.REQUEST_VERIFICATION: CaseStatus.NEEDS_EVIDENCE,
    CaseDecision.FALSE_POSITIVE: CaseStatus.RESOLVED,
}

FOLLOW_UP_ACTIONS = {
    CaseDecision.ESCALATE: "escalation_outcome",
    CaseDecision.REQUEST_VERIFICATION: "verification_outcome",
}


def ensure_case_not_closed(case: InvestigationCase) -> None:
    if case.status == CaseStatus.RESOLVED and case.decision in FOLLOW_UP_ACTIONS:
        raise HTTPException(status.HTTP_409_CONFLICT, "This case is closed and cannot be modified")


STATUS_TRANSITIONS = {
    CaseStatus.NEW: {CaseStatus.NEW, CaseStatus.NEEDS_EVIDENCE, CaseStatus.ESCALATED},
    CaseStatus.NEEDS_EVIDENCE: {CaseStatus.NEEDS_EVIDENCE, CaseStatus.ESCALATED},
    CaseStatus.ESCALATED: {CaseStatus.ESCALATED, CaseStatus.NEEDS_EVIDENCE},
    CaseStatus.RESOLVED: {CaseStatus.RESOLVED},
}


def validate_case_update(case: InvestigationCase, payload: CaseUpdate) -> None:
    """Validate the complete request before assignment, audit or SQL mutation."""
    if payload.status is None and payload.assignee is None and payload.decision is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "At least one valid case update is required"
        )
    if payload.decision is not None and case.decision is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A decision has already been recorded for this case"
        )
    ensure_case_not_closed(case)
    if case.decision is not None:
        expected = DECISION_STATUSES.get(case.decision)
        if expected != case.status or not (case.decision_reason or "").strip():
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Case state requires review before further updates"
            )
        if payload.status is not None and payload.status != expected:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "The recorded decision fixes this case's status"
            )
    if case.status == CaseStatus.RESOLVED and payload.decision is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A resolved case cannot receive a new decision"
        )
    if payload.status is not None and payload.status not in STATUS_TRANSITIONS.get(
        case.status, set()
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Unsupported case transition. Refresh the case; reopening requires a separate operation",
        )
