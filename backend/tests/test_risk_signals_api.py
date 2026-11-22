from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.routes.transactions import risk_signals
from app.core.database import Base
from app.main import create_app
from app.models.finance import Transaction
from app.models.user import User


def test_risk_signals_api_requires_auth_and_isolates_user_data():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            owner = User(email="risk-owner@example.invalid", full_name="Owner", password_hash="x")
            other = User(email="risk-other@example.invalid", full_name="Other", password_hash="x")
            db.add_all([owner, other])
            db.flush()
            db.add_all(
                [
                    Transaction(
                        user_id=owner.id,
                        posted_at=date(2026, 1, day),
                        merchant="Owner Vendor",
                        amount=Decimal("-10.00"),
                        currency="EUR",
                    )
                    for day in (1, 2)
                ]
                + [
                    Transaction(
                        user_id=other.id,
                        posted_at=date(2026, 1, day),
                        merchant="Other Vendor",
                        amount=Decimal("-999.00"),
                        currency="EUR",
                    )
                    for day in (1, 2, 3)
                ]
            )
            db.commit()
            app = create_app()

            operation = app.openapi()["paths"]["/api/transactions/risk-signals"]["get"]
            assert operation["security"] == [{"BearerAuth": []}]
            parameters = {item["name"]: item for item in operation["parameters"]}
            assert parameters["start_date"]["required"] is True
            assert parameters["end_date"]["required"] is True

            body = risk_signals(
                user=owner,
                db=db,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 31),
                max_records=1000,
            )
            duplicates = [
                signal for signal in body if signal.signal_type == "duplicate_payment_candidate"
            ]
            assert len(duplicates) == 1
            assert duplicates[0].evidence["amount"] == "10.00"
            assert all("999" not in str(signal) for signal in body)
    finally:
        engine.dispose()


def test_risk_signals_api_rejects_reversed_oversized_or_overflowing_requests():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            owner = User(email="risk-limit@example.invalid", full_name="Owner", password_hash="x")
            db.add(owner)
            db.flush()
            db.add_all(
                [
                    Transaction(
                        user_id=owner.id,
                        posted_at=date(2026, 1, index),
                        merchant=f"Vendor {index}",
                        amount=Decimal("-10.00"),
                        currency="EUR",
                    )
                    for index in range(1, 4)
                ]
            )
            db.commit()
            boundary = risk_signals(
                user=owner,
                db=db,
                start_date=date(2025, 1, 1),
                end_date=date(2026, 1, 1),
                max_records=1000,
            )
            assert isinstance(boundary, list)
            cases = [
                (date(2026, 2, 1), date(2026, 1, 1), 1000, "end_date"),
                (date(2025, 1, 1), date(2026, 1, 2), 1000, "366 days"),
                (date(2026, 1, 1), date(2026, 1, 31), 2, "record limit"),
                (date(2026, 1, 1), date(2026, 1, 31), 0, "max_records"),
            ]
            for start_date, end_date, max_records, message in cases:
                with pytest.raises(HTTPException) as exc:
                    risk_signals(
                        user=owner,
                        db=db,
                        start_date=start_date,
                        end_date=end_date,
                        max_records=max_records,
                    )
                assert exc.value.status_code == 422
                assert message in exc.value.detail
    finally:
        engine.dispose()
