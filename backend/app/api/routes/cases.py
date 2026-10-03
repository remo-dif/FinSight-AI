from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.case import CaseNote
from app.models.user import User
from app.repositories.cases import CaseRecord, CaseRepository
from app.schemas.cases import (
    CaseDecision,
    CaseDetailResponse,
    CaseNoteCreate,
    CaseNoteResponse,
    CaseResponse,
    CaseStatus,
    CaseUpdate,
)
from app.services.audit import AuditService

router = APIRouter(prefix="/cases", tags=["cases"])


def _case_response(record: CaseRecord, user: User) -> CaseResponse:
    case, transaction, assignee = record
    return CaseResponse(
        id=transaction.id,
        posted_at=transaction.posted_at,
        merchant=transaction.merchant,
        description=transaction.description,
        amount=transaction.amount,
        currency=transaction.currency,
        category=transaction.category,
        source=transaction.source,
        status=CaseStatus(case.status),
        assignee_name=assignee.full_name if assignee else None,
        assigned_to_me=case.assignee_user_id == user.id,
        decision=CaseDecision(case.decision) if case.decision else None,
        decision_reason=case.decision_reason,
        updated_at=case.updated_at,
    )


def _get_case_record(case_id: UUID, user: User, db: Session) -> CaseRecord:
    record = CaseRepository(db).get_for_user(case_id, user.id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return record


@router.get("", response_model=list[CaseResponse])
def list_cases(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CaseResponse]:
    return [_case_response(record, user) for record in CaseRepository(db).list_for_user(user.id, limit, offset)]


@router.get("/{case_id}", response_model=CaseDetailResponse)
def get_case(
    case_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CaseDetailResponse:
    record = _get_case_record(case_id, user, db)
    notes = CaseRepository(db).notes_for_user(case_id, user.id)
    return CaseDetailResponse(
        **_case_response(record, user).model_dump(),
        notes=[
            CaseNoteResponse(
                id=note.id,
                author_name=author.full_name if author else "Former analyst",
                content=note.content,
                created_at=note.created_at,
            )
            for note, author in notes
        ],
    )


@router.patch("/{case_id}", response_model=CaseResponse)
def update_case(
    case_id: UUID,
    payload: CaseUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CaseResponse:
    case, _, _ = _get_case_record(case_id, user, db)
    if payload.status is None and payload.assignee is None and payload.decision is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "At least one valid case update is required",
        )
    if payload.status == CaseStatus.RESOLVED and case.decision is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Record an investigation decision before resolving the case")

    audit = AuditService(db)
    if payload.assignee is not None:
        assignee_id = user.id if payload.assignee == "me" else None
        if case.assignee_user_id != assignee_id:
            previous_assignee_id = case.assignee_user_id
            case.assignee_user_id = assignee_id
            audit.record(
                "case.assigned",
                user.id,
                {
                    "case_id": str(case_id),
                    "previous_assignee_id": str(previous_assignee_id) if previous_assignee_id else None,
                    "assignee_id": str(assignee_id) if assignee_id else None,
                },
            )

    if payload.status is not None and case.status != payload.status.value:
        previous_status = case.status
        case.status = payload.status.value
        audit.record(
            "case.status_changed",
            user.id,
            {"case_id": str(case_id), "from": previous_status, "to": case.status},
        )

    if payload.decision is not None:
        if case.decision is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "A decision has already been recorded for this case")
        previous_status = case.status
        next_status = {
            CaseDecision.ESCALATE: CaseStatus.ESCALATED,
            CaseDecision.REQUEST_VERIFICATION: CaseStatus.NEEDS_EVIDENCE,
            CaseDecision.FALSE_POSITIVE: CaseStatus.RESOLVED,
        }[payload.decision]
        case.decision = payload.decision.value
        case.decision_reason = payload.reason
        case.status = next_status.value
        audit.record(
            "case.decision_recorded",
            user.id,
            {
                "case_id": str(case_id),
                "decision": case.decision,
                "from_status": previous_status,
                "to_status": case.status,
            },
        )

    db.commit()
    updated = _get_case_record(case_id, user, db)
    return _case_response(updated, user)


@router.post("/{case_id}/notes", response_model=CaseNoteResponse, status_code=status.HTTP_201_CREATED)
def add_case_note(
    case_id: UUID,
    payload: CaseNoteCreate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> CaseNoteResponse:
    _get_case_record(case_id, user, db)
    note = CaseNote(case_id=case_id, author_id=user.id, content=payload.content)
    db.add(note)
    AuditService(db).record("case.note_added", user.id, {"case_id": str(case_id)})
    db.commit()
    db.refresh(note)
    return CaseNoteResponse(
        id=note.id,
        author_name=user.full_name,
        content=note.content,
        created_at=note.created_at,
    )
