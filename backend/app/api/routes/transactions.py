from datetime import date
from typing import Annotated

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
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
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
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    if len(payload) > 500:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Too many transactions")
    rows = TransactionRepository(db).create_many(user.id, payload)
    db.commit()
    return rows


@router.get("/summary/{month}", response_model=MonthlySummary)
def monthly_summary(
    month: Annotated[str, Path(pattern=r"^\d{4}-\d{2}$")],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    analytics = FinanceAnalyticsService(TransactionRepository(db))
    return analytics.get_monthly_summary(user.id, month)
