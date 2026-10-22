from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TransactionCreate(BaseModel):
    posted_at: date
    merchant: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    amount: Decimal = Field(max_digits=12, decimal_places=2, allow_inf_nan=False)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    category: str = Field(default="Uncategorized", min_length=1, max_length=80)
    source: str = Field(default="manual", min_length=1, max_length=40)

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        if not isinstance(value, str) or not value.isascii() or not value.isalpha():
            raise ValueError("Currency must be a three-letter code")
        return value.upper()


class TransactionResponse(TransactionCreate):
    id: UUID

    model_config = ConfigDict(from_attributes=True)


class MonthlySummary(BaseModel):
    month: str
    income: Decimal
    spending: Decimal
    net_cash_flow: Decimal


class CategorySpend(BaseModel):
    category: str
    amount: Decimal


class MerchantSpend(BaseModel):
    merchant: str
    amount: Decimal


class Anomaly(BaseModel):
    transaction_id: UUID
    merchant: str
    amount: Decimal
    reason: str


class RecurringPayment(BaseModel):
    merchant: str
    amount: Decimal
    cadence: str
    confidence: float
