"""Idempotent, offline synthetic case data for local customer-discovery demos."""

from datetime import date, timedelta
from decimal import Decimal
from random import Random
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.finance import Transaction
from app.models.user import User
from app.repositories.transactions import TransactionRepository
from app.schemas.finance import TransactionCreate
from app.services.risk_signals import evaluate_risk_signals

DEMO_EMAIL = "synthetic-demo@finsight.invalid"
DEMO_PASSWORD = "SyntheticDemo2026!"  # Development only; never use on a deployed instance.
DEMO_ID = uuid5(NAMESPACE_URL, "finsight-ai/synthetic-demo/v1")
SOURCE = "synthetic_demo_v1"


def demo_transactions() -> list[TransactionCreate]:
    rng = Random(20261125)
    base = date(2026, 1, 1)
    merchants = ("Demo Market", "Demo Transit", "Demo Cafe", "Demo Pharmacy")
    rows = [
        TransactionCreate(
            posted_at=base + timedelta(days=index // 2),
            merchant=merchants[index % len(merchants)],
            description=f"Synthetic demo row {index + 1:03d}",
            amount=Decimal(-rng.randrange(8, 42)),
            currency="EUR",
            category="Synthetic spending",
            source=SOURCE,
        )
        for index in range(140)
    ]
    anomalies = [
        (70, "Demo Market", "-400.00"),
        (71, "Demo Duplicate", "-23.00"),
        (72, "Demo Duplicate", "-23.00"),
        (73, "Demo New Merchant", "-19.00"),
        (74, "Demo Market", "-11.00"),
        (74, "Demo Transit", "-12.00"),
        (74, "Demo Cafe", "-13.00"),
        (75, "Demo Pharmacy", "-14.00"),
        (76, "Demo Market", "-15.00"),
        (77, "Demo Transit", "-16.00"),
    ]
    for index, (day, merchant, amount) in enumerate(anomalies, start=141):
        rows.append(
            TransactionCreate(
                posted_at=base + timedelta(days=day),
                merchant=merchant,
                description=f"Synthetic demo row {index:03d}",
                amount=Decimal(amount),
                currency="EUR",
                category="Synthetic spending",
                source=SOURCE,
            )
        )
    return rows


def ensure_development() -> None:
    if settings.app_env != "development" or settings.storage_backend != "local":
        raise RuntimeError("Synthetic seed requires APP_ENV=development and STORAGE_BACKEND=local")


def seed() -> dict[str, int]:
    ensure_development()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is not None and user.id != DEMO_ID:
            raise RuntimeError("Demo email is already owned by a different account")
        try:
            if user is None:
                user = User(
                    id=DEMO_ID,
                    email=DEMO_EMAIL,
                    full_name="Synthetic Demo Analyst",
                    password_hash=hash_password(DEMO_PASSWORD),
                )
                db.add(user)
                db.flush()
            existing = {
                row.description
                for row in db.scalars(
                    select(Transaction).where(
                        Transaction.user_id == DEMO_ID, Transaction.source == SOURCE
                    )
                )
            }
            expected = demo_transactions()
            missing = [row for row in expected if row.description not in existing]
            if missing:
                TransactionRepository(db).create_many(DEMO_ID, missing)
            db.flush()
            all_demo = list(
                db.scalars(
                    select(Transaction)
                    .where(Transaction.user_id == DEMO_ID, Transaction.source == SOURCE)
                    .order_by(Transaction.posted_at, Transaction.id)
                )
            )
            signal_types = {signal.signal_type for signal in evaluate_risk_signals(all_demo)}
            required = {
                "duplicate_payment_candidate",
                "daily_velocity",
                "amount_deviation",
                "new_merchant",
            }
            if not required <= signal_types:
                raise RuntimeError(
                    f"Synthetic seed did not exercise all expected rules: {required - signal_types}"
                )
            db.commit()
            return {
                "transactions": len(all_demo),
                "created": len(missing),
                "signals": len(signal_types),
            }
        except Exception:
            db.rollback()
            raise


if __name__ == "__main__":
    result = seed()
    print(
        f"Synthetic demo: {result['transactions']} transactions, {result['created']} created, {result['signals']} signal types verified"
    )
