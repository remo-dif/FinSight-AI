import hashlib
import io
import json
import socket
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
import pdfplumber
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.routes.cases import export_dossier_json, export_dossier_pdf
from app.core.config import settings
from app.core.database import Base, get_db
from app.core.security import TokenType, create_token
from app.main import create_app
from app.models.audit import AuditLog
from app.models.case import CaseNote, InvestigationCase
from app.models.finance import Transaction, UploadedFile
from app.models.user import User
from app.services.ingestion import IngestionService
from app.services.risk_signals import evaluate_risk_signals
from app.services.dossier import FORMAT_VERSION, canonical_bytes
from scripts import seed_demo
from scripts.seed_demo import demo_transactions, ensure_development


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def add_case(db: Session, *, currency: str = "EUR") -> tuple[User, Transaction]:
    user = User(
        email=f"{uuid4()}@example.invalid", full_name="Analista Èva", password_hash="unused"
    )
    db.add(user)
    db.flush()
    transaction = Transaction(
        user_id=user.id,
        posted_at=date(2026, 5, 4),
        merchant="Caffè Milano",
        description="Synthetic",
        amount=Decimal("-14.20"),
        currency=currency,
        category="Food",
        source="csv",
    )
    db.add(transaction)
    db.flush()
    db.add(InvestigationCase(transaction_id=transaction.id))
    db.commit()
    return user, transaction


def test_canonical_bytes_sort_keys_lists_are_explicit_and_reject_floats():
    first = {"z": Decimal("1.20"), "a": "Cafe\u0301", "items": [1, 2], "date": date(2026, 5, 4)}
    second = {"items": [1, 2], "date": date(2026, 5, 4), "a": "Café", "z": Decimal("1.20")}
    assert canonical_bytes(first) == canonical_bytes(second)
    assert (
        canonical_bytes(first).decode("utf-8")
        == '{"a":"Café","date":"2026-05-04","items":[1,2],"z":"1.20"}'
    )
    with pytest.raises(ValueError, match="floating-point"):
        canonical_bytes({"bad": 1.0})
    with pytest.raises(ValueError, match="non-finite"):
        canonical_bytes({"bad": Decimal("NaN")})


def test_exports_share_hash_exclude_export_events_and_track_changes(db: Session):
    user, transaction = add_case(db)
    first = export_dossier_json(transaction.id, user, db)
    second = export_dossier_json(transaction.id, user, db)
    digest = hashlib.sha256(first.body).hexdigest()
    assert first.body == second.body
    assert first.headers["x-dossier-sha256"] == second.headers["x-dossier-sha256"] == digest
    assert first.headers["x-dossier-format-version"] == FORMAT_VERSION
    assert first.headers["cache-control"].startswith("private, no-store")
    assert first.headers["content-disposition"].endswith('dossier.json"')
    data = json.loads(first.body)
    assert data["transaction"]["amount"] == "-14.20"
    assert data["transaction"]["currency"] == "EUR"
    assert data["transaction"]["posted_at"] == "2026-05-04"
    assert data["audit_events"] == []
    events = list(db.scalars(select(AuditLog).where(AuditLog.action.like("case.dossier_export%"))))
    assert len(events) == 2
    assert all(event.metadata_json["sha256"] == digest for event in events)

    note = CaseNote(case_id=transaction.id, author_id=user.id, content="È una nota")
    db.add(note)
    db.commit()
    changed = export_dossier_json(transaction.id, user, db)
    assert changed.headers["x-dossier-sha256"] != digest
    db.add(
        UploadedFile(
            user_id=user.id,
            filename="prova.pdf",
            content_type="application/pdf",
            storage_path="private/path",
            status="indexed",
        )
    )
    db.commit()
    evidence_changed = export_dossier_json(transaction.id, user, db)
    assert evidence_changed.headers["x-dossier-sha256"] != changed.headers["x-dossier-sha256"]
    assert b"private/path" not in evidence_changed.body

    db.add(
        Transaction(
            user_id=user.id,
            posted_at=date(2026, 5, 5),
            merchant="USD shop",
            description="Other currency",
            amount=Decimal("-31.12"),
            currency="USD",
            category="Other",
            source="csv",
        )
    )
    db.commit()
    usd_changed = export_dossier_json(transaction.id, user, db)
    assert usd_changed.headers["x-dossier-sha256"] == evidence_changed.headers["x-dossier-sha256"]
    assert json.loads(usd_changed.body)["transaction"]["currency"] == "EUR"

    usd_row = db.scalar(select(Transaction).where(Transaction.merchant == "USD shop"))
    db.add(InvestigationCase(transaction_id=usd_row.id))
    db.commit()
    usd_case = json.loads(export_dossier_json(usd_row.id, user, db).body)
    assert (usd_case["transaction"]["amount"], usd_case["transaction"]["currency"]) == (
        "-31.12",
        "USD",
    )

    case = db.get(InvestigationCase, transaction.id)
    case.decision = "escalate"
    case.decision_reason = "Needs review"
    db.commit()
    decision_changed = export_dossier_json(transaction.id, user, db)
    assert decision_changed.headers["x-dossier-sha256"] != usd_changed.headers["x-dossier-sha256"]


def test_pdf_unicode_long_note_all_pages_have_complete_footer(db: Session):
    user, transaction = add_case(db)
    for index in range(18):
        db.add(
            CaseNote(
                case_id=transaction.id,
                author_id=user.id,
                content=f"Nota italiana {index}: " + "È" * 1500,
            )
        )
    db.commit()
    json_response = export_dossier_json(transaction.id, user, db)
    pdf_response = export_dossier_pdf(transaction.id, user, db)
    assert pdf_response.body.startswith(b"%PDF-")
    assert pdf_response.headers["x-dossier-sha256"] == json_response.headers["x-dossier-sha256"]
    with pdfplumber.open(io.BytesIO(pdf_response.body)) as pdf:
        assert len(pdf.pages) > 1
        for index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            assert json_response.headers["x-dossier-sha256"] in text
            assert f"Page {index}" in text
            assert "not a digital signature" in " ".join(text.split())
        assert "Caffè Milano" in (pdf.pages[0].extract_text() or "")


def test_exports_make_no_outbound_connection(db: Session, monkeypatch):
    user, transaction = add_case(db)

    def fail_connect(*_args, **_kwargs):
        raise AssertionError("Export attempted an outbound connection")

    monkeypatch.setattr(socket.socket, "connect", fail_connect)
    assert export_dossier_json(transaction.id, user, db).body
    assert export_dossier_pdf(transaction.id, user, db).body.startswith(b"%PDF-")


@pytest.mark.asyncio
async def test_http_owner_and_other_user_access(db: Session):
    owner, transaction = add_case(db)
    other = User(email="other@example.invalid", full_name="Other", password_hash="unused")
    db.add(other)
    db.commit()
    app = create_app()

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        for suffix in ("pdf", "json"):
            path = f"/api/cases/{transaction.id}/dossier.{suffix}"
            own = await client.get(
                path,
                headers={"Authorization": f"Bearer {create_token(owner.id, TokenType.ACCESS)}"},
            )
            denied = await client.get(
                path,
                headers={"Authorization": f"Bearer {create_token(other.id, TokenType.ACCESS)}"},
            )
            assert own.status_code == 200
            assert denied.status_code == 404
            assert own.headers["content-type"].startswith("application/")
            assert own.headers["x-dossier-sha256"]


def test_seed_data_exercises_existing_rules_and_production_guard(monkeypatch):
    rows = []
    for item in demo_transactions():
        transaction = Transaction(id=uuid4(), user_id=uuid4(), **item.model_dump())
        rows.append(transaction)
    types = {signal.signal_type for signal in evaluate_risk_signals(rows)}
    assert {
        "duplicate_payment_candidate",
        "daily_velocity",
        "amount_deviation",
        "new_merchant",
    } <= types
    assert len(rows) == 150
    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(RuntimeError, match="development"):
        ensure_development()


def test_seed_is_repeatable_and_preserves_unrelated_rows(db: Session, monkeypatch):
    monkeypatch.setattr(
        seed_demo,
        "SessionLocal",
        lambda: sessionmaker(bind=db.get_bind(), expire_on_commit=False)(),
    )
    unrelated, transaction = add_case(db)
    original = (transaction.id, transaction.amount, transaction.merchant)
    first = seed_demo.seed()
    second = seed_demo.seed()
    assert first["created"] == 150
    assert second["created"] == 0
    assert db.get(Transaction, transaction.id).amount == original[1]
    assert db.get(Transaction, transaction.id).merchant == original[2]
    assert db.get(User, unrelated.id) is not None


def test_manual_csv_uses_existing_ingestion_and_rules():
    payload = (Path(__file__).parent / "fixtures" / "synthetic_demo_import.csv").read_bytes()
    imported = IngestionService().parse_csv(payload)
    assert len(imported) == 24
    assert {item.currency for item in imported} == {"EUR"}
    rows = [Transaction(id=uuid4(), user_id=uuid4(), **item.model_dump()) for item in imported]
    types = {signal.signal_type for signal in evaluate_risk_signals(rows)}
    assert types == {
        "duplicate_payment_candidate",
        "daily_velocity",
        "amount_deviation",
        "new_merchant",
    }
