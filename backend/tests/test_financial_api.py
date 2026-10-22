from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.core.database import Base, get_db
from app.core.security import get_current_user
from app.main import create_app
from app.models.finance import Transaction
from app.models.user import User


@pytest.mark.asyncio
async def test_summary_and_evidence_api_preserve_currency_and_user_isolation():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            owner = User(
                email="owner@example.invalid", full_name="Synthetic", password_hash="unused"
            )
            other = User(
                email="other@example.invalid", full_name="Synthetic", password_hash="unused"
            )
            db.add_all([owner, other])
            db.flush()
            db.add_all(
                [
                    Transaction(
                        user_id=owner.id,
                        posted_at=date(2025, 1, 1),
                        merchant="Synthetic",
                        amount=Decimal("-10.25"),
                        currency="EUR",
                        category="Groceries",
                    ),
                    Transaction(
                        user_id=owner.id,
                        posted_at=date(2025, 1, 1),
                        merchant="Synthetic",
                        amount=Decimal("-90.00"),
                        currency="USD",
                        category="Groceries",
                    ),
                    Transaction(
                        user_id=other.id,
                        posted_at=date(2025, 1, 1),
                        merchant="Other",
                        amount=Decimal("-999.00"),
                        currency="EUR",
                        category="Groceries",
                    ),
                ]
            )
            db.commit()
            app = create_app()

            def override_db():
                yield db

            app.dependency_overrides[get_db] = override_db
            app.dependency_overrides[get_current_user] = lambda: owner
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                mixed = await client.get("/api/transactions/summary/2025-01")
                assert mixed.status_code == 422
                summary = await client.get("/api/transactions/summary/2025-01?currency=EUR")
                assert summary.status_code == 200
                assert summary.json()["spending"] == "10.25"
                assert summary.json()["currency"] == "EUR"
                report = await client.get("/api/transactions/spending/2025-01?currency=EUR")
                assert report.status_code == 200
                assert report.json()["net_spending"] == "10.25"
                assert len(report.json()["_evidence"]["source_transaction_ids"]) == 1
                comparison = await client.get(
                    "/api/transactions/spending/2025-02?currency=EUR&compare_to=2025-01"
                )
                assert comparison.status_code == 200
                assert comparison.json()["spending_delta"] == "-10.25"
                invalid = await client.get("/api/transactions/summary/2025-13?currency=EUR")
                assert invalid.status_code == 422
                invalid = await client.get(
                    "/api/transactions/spending/2025-01?currency=EUR&compare_to=2025-13"
                )
                assert invalid.status_code == 422
                invalid = await client.get("/api/transactions/summary/2025-01?currency=12A")
                assert invalid.status_code == 422
    finally:
        engine.dispose()
