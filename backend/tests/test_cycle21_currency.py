from datetime import date
from decimal import Decimal
from io import BytesIO

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from starlette.datastructures import Headers, UploadFile

from app.api.routes.uploads import upload_user
from app.core.database import Base, get_async_db
from app.main import create_app
from app.models.finance import Transaction, UploadedFile
from app.models.user import User
from app.services.document_ingestion import DocumentIngestionService
from app.services.ingestion import IngestionService
from tests.test_cycle2_uploads import AsyncAdapter, configure


@pytest.fixture(params=[IngestionService, DocumentIngestionService])
def parser(request):
    return request.param()


def csv(rows, header="currency"):
    return f"date,merchant,amount,{header}\n{rows}".encode()


@pytest.mark.parametrize("code", ["EUR", "USD", " eur "])
def test_explicit_currency_is_preserved(parser, code):
    rows = parser.parse_csv(csv(f"2025-01-01,Synthetic,-1.20,{code}\n"))
    assert rows[0].currency == code.strip().upper()
    assert rows[0].amount == Decimal("-1.20")


@pytest.mark.parametrize("header", ["currency", " Currency "])
def test_missing_currency_never_defaults(parser, header):
    with pytest.raises(Exception) as exc:
        parser.parse_csv(csv("2025-01-01,Synthetic,-1.20,\n", header))
    assert exc.value.status_code == 400
    assert "line 2" in exc.value.detail and "select" in exc.value.detail.lower()


def test_absent_column_requires_selection(parser):
    payload = b"date,merchant,amount\n2025-01-01,Synthetic,-1.20\n"
    with pytest.raises(Exception) as exc:
        parser.parse_csv(payload)
    assert exc.value.status_code == 400
    assert parser.parse_csv(payload, import_currency="EUR")[0].currency == "EUR"


@pytest.mark.parametrize("code", ["XYZ", "SEK", "12A", "EURO", "€"])
def test_invalid_row_is_not_replaced_by_selection(parser, code):
    with pytest.raises(Exception) as exc:
        parser.parse_csv(csv(f"2025-01-01,Synthetic,-1.20,{code}\n"), import_currency="EUR")
    assert exc.value.status_code == 400
    assert "currency" in exc.value.detail.lower()


def test_conflict_and_invalid_import_selection(parser):
    payload = csv("2025-01-01,Synthetic,-1.20,USD\n")
    for code in ["EUR", "XYZ", "   "]:
        with pytest.raises(Exception) as exc:
            parser.parse_csv(payload, import_currency=code)
        assert exc.value.status_code == 400


def test_mixed_explicit_currencies_without_selection(parser):
    rows = parser.parse_csv(csv("2025-01-01,A,-1.20,EUR\n2025-01-02,B,-2.30,USD\n"))
    assert [row.currency for row in rows] == ["EUR", "USD"]


@pytest.mark.parametrize("header", ["currency,currency", "currency,Currency", " Currency , currency "])
def test_duplicate_currency_headers_rejected_even_without_rows(parser, header):
    with pytest.raises(Exception) as exc:
        parser.parse_csv(csv("", header))
    assert exc.value.status_code == 400
    assert "duplicate" in exc.value.detail.lower()


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_code,selection", [("", None), ("XYZ", None), ("12A", None), ("USD", "EUR"), (None, "EUR")])
async def test_upload_atomic_currency_validation_and_user_isolation(monkeypatch, tmp_path, bad_code, selection):
    configure(monkeypatch, upload_dir=tmp_path, storage_backend="local")
    sentinel = tmp_path / "pre-existing.csv"
    sentinel.write_bytes(b"Keep existing upload")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as db:
            owner = User(email="owner@synthetic.invalid", full_name="Owner", password_hash="unused")
            other = User(email="other@synthetic.invalid", full_name="Other", password_hash="unused")
            db.add_all([owner, other])
            db.flush()
            existing = Transaction(user_id=other.id, posted_at=date(2025, 1, 1), merchant="Existing", amount=Decimal("-9.00"), currency="USD", category="Other")
            db.add(existing)
            db.commit()
            app = create_app()
            app.dependency_overrides[upload_user] = lambda: owner
            app.dependency_overrides[get_async_db] = lambda: AsyncAdapter(db)
            second = "EUR" if bad_code is None else bad_code
            payload = csv(f"2025-01-01,A,-1.20,EUR\n2025-01-02,B,-2.30,{second}\n")
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/api/uploads", files={"file": ("data.csv", payload, "text/csv")}, data={} if selection is None else {"import_currency": selection})
            assert response.status_code == (200 if bad_code is None else 400), response.text
            assert db.scalar(select(func.count()).select_from(UploadedFile)) == (1 if bad_code is None else 0)
            owned = list(db.scalars(select(Transaction).where(Transaction.user_id == owner.id)))
            assert len(owned) == (2 if bad_code is None else 0)
            assert all(row.currency == "EUR" for row in owned)
            assert db.get(Transaction, existing.id).currency == "USD"
            assert sentinel.read_bytes() == b"Keep existing upload"
            if bad_code is not None:
                assert list((tmp_path / "staging").rglob("*.csv")) == []
    finally:
        engine.dispose()
