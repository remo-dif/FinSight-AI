import io
import json
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pdfplumber
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.routes.cases import (
    export_dossier_json,
    export_dossier_pdf,
    link_case_document,
    list_case_documents,
    unlink_case_document,
)
from app.core.database import Base
from app.models.audit import AuditLog
from app.models.case import CaseDocumentLink, InvestigationCase
from app.models.finance import Transaction, UploadedFile
from app.models.user import User
from app.schemas.cases import CaseDocumentLinkCreate


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def add_case(db: Session, name: str) -> tuple[User, Transaction]:
    user = User(email=f"{uuid4()}@example.invalid", full_name=name, password_hash="unused")
    db.add(user)
    db.flush()
    transaction = Transaction(
        user_id=user.id,
        posted_at=date(2026, 5, 4),
        merchant="Synthetic merchant",
        description="Synthetic",
        amount=Decimal("-14.20"),
        currency="EUR",
        category="Food",
        source="csv",
    )
    db.add(transaction)
    db.flush()
    db.add(InvestigationCase(transaction_id=transaction.id))
    db.commit()
    return user, transaction


def add_upload(db: Session, user: User, filename: str) -> UploadedFile:
    upload = UploadedFile(
        user_id=user.id,
        filename=filename,
        content_type="application/pdf",
        storage_path=f"private/{filename}",
        status="indexed",
    )
    db.add(upload)
    db.commit()
    return upload


def test_only_linked_documents_appear_and_link_events_change_hash(db: Session):
    owner, case = add_case(db, "Owner")
    linked = add_upload(db, owner, "linked.pdf")
    unlinked = add_upload(db, owner, "other-client.pdf")
    before = export_dossier_json(case.id, owner, db)
    assert json.loads(before.body)["evidence"] == []
    original_revision = db.get(InvestigationCase, case.id).revision

    result = link_case_document(
        case.id, CaseDocumentLinkCreate(uploaded_file_id=linked.id), owner, db
    )
    assert result.id == linked.id
    assert result.linked_by == owner.id
    assert result.linked_by_name == "Owner"
    assert [row.id for row in list_case_documents(case.id, owner, db)] == [linked.id]
    db.expire_all()
    assert db.get(InvestigationCase, case.id).revision == original_revision + 1

    first = export_dossier_json(case.id, owner, db)
    second = export_dossier_json(case.id, owner, db)
    assert first.headers["x-dossier-sha256"] != before.headers["x-dossier-sha256"]
    assert first.headers["x-dossier-sha256"] == second.headers["x-dossier-sha256"]
    data = json.loads(first.body)
    assert [item["filename"] for item in data["evidence"]] == ["linked.pdf"]
    assert data["evidence"][0]["linked_by"] == str(owner.id)
    assert data["evidence"][0]["linked_at"]
    assert "other-client.pdf" not in first.body.decode("utf-8")
    assert [item["action"] for item in data["audit_events"]] == ["case.document_linked"]

    pdf = export_dossier_pdf(case.id, owner, db)
    with pdfplumber.open(io.BytesIO(pdf.body)) as document:
        text = "\n".join(page.extract_text() or "" for page in document.pages)
    assert "linked.pdf" in text
    assert "other-client.pdf" not in text

    unlink_case_document(case.id, linked.id, owner, db)
    db.expire_all()
    assert db.get(InvestigationCase, case.id).revision == original_revision + 2
    after = export_dossier_json(case.id, owner, db)
    assert after.headers["x-dossier-sha256"] != first.headers["x-dossier-sha256"]
    assert json.loads(after.body)["evidence"] == []
    assert {item["action"] for item in json.loads(after.body)["audit_events"]} == {
        "case.document_linked",
        "case.document_unlinked",
    }
    events = list(db.scalars(select(AuditLog).where(AuditLog.action.like("case.document_%"))))
    assert [event.metadata_json["file_id"] for event in events] == [str(linked.id)] * 2
    assert all(event.metadata_json["filename"] == "linked.pdf" for event in events)
    assert unlinked.id != linked.id


def test_ownership_is_checked_for_both_case_and_upload(db: Session):
    owner, case = add_case(db, "Owner")
    other, other_case = add_case(db, "Other")
    own_upload = add_upload(db, owner, "own.pdf")
    other_upload = add_upload(db, other, "other.pdf")

    for case_id, file_id, caller in (
        (case.id, other_upload.id, owner),
        (other_case.id, own_upload.id, owner),
        (case.id, own_upload.id, other),
    ):
        with pytest.raises(HTTPException) as error:
            link_case_document(
                case_id, CaseDocumentLinkCreate(uploaded_file_id=file_id), caller, db
            )
        assert error.value.status_code == 404
    assert list_case_documents(case.id, owner, db) == []
    with pytest.raises(HTTPException) as error:
        list_case_documents(other_case.id, owner, db)
    assert error.value.status_code == 404

    link_case_document(case.id, CaseDocumentLinkCreate(uploaded_file_id=own_upload.id), owner, db)
    for case_id, file_id, caller in (
        (case.id, own_upload.id, other),
        (other_case.id, own_upload.id, owner),
        (case.id, other_upload.id, owner),
    ):
        with pytest.raises(HTTPException) as error:
            unlink_case_document(case_id, file_id, caller, db)
        assert error.value.status_code == 404


def test_duplicate_and_closed_case_links_are_rejected(db: Session):
    owner, case = add_case(db, "Owner")
    upload = add_upload(db, owner, "evidence.pdf")
    another = add_upload(db, owner, "another.pdf")
    link_case_document(case.id, CaseDocumentLinkCreate(uploaded_file_id=upload.id), owner, db)
    with pytest.raises(HTTPException) as duplicate:
        link_case_document(case.id, CaseDocumentLinkCreate(uploaded_file_id=upload.id), owner, db)
    assert duplicate.value.status_code == 409
    assert db.scalar(select(CaseDocumentLink).where(CaseDocumentLink.case_id == case.id))

    record = db.get(InvestigationCase, case.id)
    record.status = "resolved"
    record.decision = "escalate"
    record.decision_reason = "Reviewed"
    db.commit()
    with pytest.raises(HTTPException) as denied_link:
        link_case_document(case.id, CaseDocumentLinkCreate(uploaded_file_id=another.id), owner, db)
    assert denied_link.value.status_code == 409
    with pytest.raises(HTTPException) as denied_unlink:
        unlink_case_document(case.id, upload.id, owner, db)
    assert denied_unlink.value.status_code == 409
    assert [item.id for item in list_case_documents(case.id, owner, db)] == [upload.id]

    # A resolved false positive has no V2 follow-up closure and remains editable.
    false_positive_owner, false_positive_case = add_case(db, "False positive owner")
    false_positive_upload = add_upload(db, false_positive_owner, "review.pdf")
    false_positive_record = db.get(InvestigationCase, false_positive_case.id)
    false_positive_record.status = "resolved"
    false_positive_record.decision = "false_positive"
    false_positive_record.decision_reason = "Reviewed"
    db.commit()
    assert (
        link_case_document(
            false_positive_case.id,
            CaseDocumentLinkCreate(uploaded_file_id=false_positive_upload.id),
            false_positive_owner,
            db,
        ).id
        == false_positive_upload.id
    )


def test_linked_upload_cannot_be_deleted_without_unlinking(db: Session):
    owner, case = add_case(db, "Owner")
    upload = add_upload(db, owner, "evidence.pdf")
    link_case_document(case.id, CaseDocumentLinkCreate(uploaded_file_id=upload.id), owner, db)
    db.delete(upload)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert db.get(UploadedFile, upload.id) is not None
    assert [item.id for item in list_case_documents(case.id, owner, db)] == [upload.id]

    unlink_case_document(case.id, upload.id, owner, db)
    db.delete(upload)
    db.commit()
    assert db.get(UploadedFile, upload.id) is None


def test_deleting_case_removes_document_links(db: Session):
    owner, case = add_case(db, "Owner")
    upload = add_upload(db, owner, "evidence.pdf")
    link_case_document(case.id, CaseDocumentLinkCreate(uploaded_file_id=upload.id), owner, db)
    db.delete(db.get(InvestigationCase, case.id))
    db.commit()
    assert db.scalar(select(CaseDocumentLink).where(CaseDocumentLink.case_id == case.id)) is None
    assert db.get(UploadedFile, upload.id) is not None
