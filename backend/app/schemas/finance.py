from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TransactionCreate(BaseModel):
    posted_at: date
    merchant: str = Field(min_length=1, max_length=200)
    description: str = ""
    amount: Decimal
    currency: str = Field(default="USD", min_length=3, max_length=3)
    category: str = "Uncategorized"
    source: str = "manual"


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
