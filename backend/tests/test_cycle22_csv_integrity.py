from decimal import Decimal

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

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


@pytest.mark.parametrize("rows", ["", "2025-01-01,Synthetic,EUR\n"])
def test_missing_amount_header_rejected_even_without_rows(parser, rows):
    with pytest.raises(HTTPException) as exc:
        parser.parse_csv(f"date,merchant,currency\n{rows}".encode())
    assert exc.value.status_code == 400
    assert "amount" in exc.value.detail.lower()


@pytest.mark.parametrize("value", ["", "   ", "\t", None])
@pytest.mark.parametrize("header", ["amount", "Amount"])
def test_missing_or_blank_amount_cell_rejected_before_categorization(parser, value, header):
    def never_categorize(*args):
        pytest.fail("Missing amount reached categorization")

    parser.categorizer.categorize = never_categorize
    row = "2025-01-01,Synthetic,EUR" + (f",{value}" if value is not None else "")
    with pytest.raises(HTTPException) as exc:
        parser.parse_csv(f"date,merchant,currency,{header}\n{row}\n".encode())
    assert exc.value.status_code == 400
    assert "amount" in exc.value.detail.lower() and "line 2" in exc.value.detail


@pytest.mark.parametrize("header", ["amount", "Amount"])
def test_explicit_zero_and_signed_values_preserve_order_currency_and_text(parser, header):
    payload = f'date,merchant,description,{header},currency\n2025-01-01,"multi\nline",first,0,EUR\n2025-01-02,B,"two\nlines",+12.34,USD\n2025-01-03,C,third,-5.67,EUR\n'.encode()
    rows = parser.parse_csv(payload)
    assert [row.amount for row in rows] == [Decimal(0), Decimal("12.34"), Decimal("-5.67")]
    assert [row.currency for row in rows] == ["EUR", "USD", "EUR"]
    assert rows[0].merchant == "multi\nline" and rows[1].description == "two\nlines"


@pytest.mark.parametrize("field", ["merchant", "description"])
@pytest.mark.parametrize("error", ["currency", "amount", "date", "precision", "length"])
def test_errors_after_multiline_records_report_physical_line(parser, field, error):
    first = (
        '2025-01-01,"multi\nline",ok,-1.00,EUR'
        if field == "merchant"
        else '2025-01-01,A,"multi\nline",-1.00,EUR'
    )
    second = {
        "currency": "2025-01-02,B,ok,-2.00,",
        "amount": "2025-01-02,B,ok,not-money,EUR",
        "date": "not-a-date,B,ok,-2.00,EUR",
        "precision": "2025-01-02,B,ok,-2.001,EUR",
        "length": f"2025-01-02,{'B' * 201},ok,-2.00,EUR",
    }[error]
    payload = f"date,merchant,description,amount,currency\n{first}\n\n{second}\n".encode()
    with pytest.raises(HTTPException) as exc:
        parser.parse_csv(payload)
    assert exc.value.status_code == 400
    assert "line 5" in exc.value.detail


def test_rejected_multiline_record_reports_its_ending_line(parser):
    payload = b'date,merchant,amount,currency\n2025-01-01,"multi\nline",-1.00,\n'
    with pytest.raises(HTTPException) as exc:
        parser.parse_csv(payload)
    assert exc.value.status_code == 400 and "line 3" in exc.value.detail


@pytest.mark.parametrize("value", ["", "garbage", "NaN", "sNaN", "Infinity", "-Infinity"])
def test_late_invalid_amount_reports_line(parser, value):
    payload = f"date,merchant,amount,currency\n2025-01-01,A,-1.20,EUR\n2025-01-02,B,{value},EUR\n".encode()
    with pytest.raises(HTTPException) as exc:
        parser.parse_csv(payload)
    assert exc.value.status_code == 400 and "line 3" in exc.value.detail


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["", "   ", "not-money", "NaN", "sNaN", "Infinity"])
async def test_upload_rejects_late_invalid_amount_without_partial_persistence(
    monkeypatch, tmp_path, value
):
    configure(monkeypatch, upload_dir=tmp_path, storage_backend="local")
    sentinel = tmp_path / "existing.csv"
    sentinel.write_bytes(b"Preserve existing file")
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as db:
            owner = User(email="owner@synthetic.invalid", full_name="Owner", password_hash="unused")
            db.add(owner)
            db.commit()
            app = create_app()
            app.dependency_overrides[upload_user] = lambda: owner
            app.dependency_overrides[get_async_db] = lambda: AsyncAdapter(db)
            payload = f'date,merchant,amount,currency\n2025-01-01,"multi\nline",-1.20,EUR\n2025-01-02,B,{value},EUR\n'.encode()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/api/uploads", files={"file": ("data.csv", payload, "text/csv")}
                )
            assert response.status_code == 400, response.text
            assert "line 4" in response.json()["detail"]
            assert db.scalar(select(func.count()).select_from(Transaction)) == 0
            assert db.scalar(select(func.count()).select_from(UploadedFile)) == 0
            assert sentinel.read_bytes() == b"Preserve existing file"
            assert list((tmp_path / "staging").rglob("*.csv")) == []
    finally:
        engine.dispose()
