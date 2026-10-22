from datetime import date
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.database import Base
from app.models.finance import Transaction
from app.models.user import User
from app.repositories.transactions import TransactionRepository
from app.schemas.finance import TransactionCreate
from app.services.analytics import FinanceAnalyticsService
from tests.fixtures.synthetic_finance import generate_dataset


def test_dataset_is_reproducible_and_schema_compatible():
    dataset = generate_dataset()
    assert dataset == generate_dataset()
    assert len(dataset["users"]) == 10
    assert len(dataset["transactions"]) == 3000
    assert len(dataset["expected_cents"]) == 120
    for row in dataset["transactions"]:
        assert TransactionCreate.model_validate(row).currency == "EUR"


def test_full_ledger_against_independent_cent_oracle():
    dataset = generate_dataset()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add_all(
                User(
                    id=UUID(u["id"]),
                    email=u["email"],
                    full_name=u["full_name"],
                    password_hash="unused",
                )
                for u in dataset["users"]
            )
            db.flush()
            for row in dataset["transactions"]:
                payload = TransactionCreate.model_validate(row).model_dump()
                db.add(Transaction(id=UUID(row["id"]), user_id=UUID(row["user_id"]), **payload))
            db.flush()
            service = FinanceAnalyticsService(TransactionRepository(db))
            for key, expected in dataset["expected_cents"].items():
                user, month = key.split("/")
                report = service.get_spending_report(UUID(user), month, "EUR")
                for field in ("income", "spending", "net_cash_flow", "net_spending", "refunds"):
                    assert Decimal(report[field]) * 100 == expected[field], (key, field)
                assert {k: Decimal(v) * 100 for k, v in report["categories"].items()} == expected[
                    "categories"
                ]
                assert len(report["internal_transfer_ids"]) == 2
                assert len(report["suspected_duplicate_ids"]) == 2
                own_ids = {
                    r["id"]
                    for r in dataset["transactions"]
                    if r["user_id"] == user and r["posted_at"].startswith(month)
                }
                for fact in report["_evidence"]["facts"]:
                    assert set(fact["transaction_ids"]) <= own_ids
            user = UUID(dataset["users"][0]["id"])
            comparison = service.compare_spending(user, "2025-07", "2025-08", "EUR")
            a = dataset["expected_cents"][f"{user}/2025-07"]
            b = dataset["expected_cents"][f"{user}/2025-08"]
            assert (
                Decimal(comparison["net_spending_delta"]) * 100
                == b["net_spending"] - a["net_spending"]
            )
            assert sum(
                Decimal(f["amount"])
                for f in comparison["_evidence"]["facts"]
                if f["key"].startswith("delta:category:")
            ) == Decimal(comparison["net_spending_delta"])
            assert service.get_spending_report(uuid4(), "2025-01", "EUR")["income"] == "0.00"
            db.add(
                Transaction(
                    user_id=user,
                    posted_at=date(2026, 1, 1),
                    merchant="Boundary",
                    amount=Decimal("999.00"),
                    currency="EUR",
                    category="Income",
                )
            )
            db.flush()
            december = service.get_spending_report(user, "2025-12", "EUR")
            assert (
                Decimal(december["income"]) * 100
                == dataset["expected_cents"][f"{user}/2025-12"]["income"]
            )
            with pytest.raises(ValueError):
                service.get_spending_report(user, "2025-13", "EUR")
    finally:
        engine.dispose()
