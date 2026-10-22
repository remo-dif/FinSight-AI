from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas.finance import TransactionCreate


@pytest.mark.parametrize("amount", ["1.001", "10000000000.00", "NaN", "Infinity"])
def test_rejects_unrepresentable_money(amount):
    with pytest.raises(ValidationError):
        TransactionCreate(posted_at=date(2025, 1, 1), merchant="Synthetic", amount=amount)


def test_currency_is_normalized():
    item = TransactionCreate(
        posted_at=date(2025, 1, 1), merchant="Synthetic", amount=Decimal("-1.20"), currency="eur"
    )
    assert item.currency == "EUR"
