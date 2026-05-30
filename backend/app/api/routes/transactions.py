from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.repositories.transactions import TransactionRepository
from app.schemas.finance import MonthlySummary, TransactionCreate, TransactionResponse
from app.services.analytics import FinanceAnalyticsService

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("", response_model=list[TransactionResponse])
def list_transactions(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return TransactionRepository(db).list_for_user(
        user.id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=list[TransactionResponse])
def create_transactions(
    payload: list[TransactionCreate],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if len(payload) > 500:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Too many transactions")
    rows = TransactionRepository(db).create_many(user.id, payload)
    db.commit()
    return rows


@router.get("/summary/{month}", response_model=MonthlySummary)
def monthly_summary(
    month: str = Path(pattern=r"^\d{4}-\d{2}$"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    analytics = FinanceAnalyticsService(TransactionRepository(db))
    return analytics.get_monthly_summary(user.id, month)
