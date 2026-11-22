from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from uuid import UUID, uuid5

NAMESPACE = UUID("87c80168-7778-40d1-b85b-20b14a6f2540")


@dataclass(frozen=True)
class RiskTransaction:
    id: UUID
    posted_at: date
    merchant: str
    amount: Decimal
    currency: str = "EUR"


def transaction(
    name: str,
    posted_at: str,
    merchant: str,
    amount: str,
    currency: str = "EUR",
) -> RiskTransaction:
    return RiskTransaction(
        id=uuid5(NAMESPACE, name),
        posted_at=date.fromisoformat(posted_at),
        merchant=merchant,
        amount=Decimal(amount),
        currency=currency,
    )
