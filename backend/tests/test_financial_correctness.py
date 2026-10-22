from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.agents.orchestrator import ReviewerAgent
from app.core.database import Base
from app.models.finance import Transaction
from app.models.user import User
from app.repositories.transactions import TransactionRepository
from app.schemas.finance import TransactionCreate
from app.services.analytics import FinanceAnalyticsService
from app.services.document_ingestion import DocumentIngestionService
from app.services.ingestion import IngestionService


@pytest.fixture
def ledger():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user_id = uuid4()
        db.add(
            User(
                id=user_id,
                email="synthetic@example.invalid",
                full_name="Synthetic",
                password_hash="unused",
            )
        )
        db.flush()
        yield db, user_id
    engine.dispose()


def add_row(db, user_id, amount, category="Groceries", currency="EUR", month=1):
    row = Transaction(
        user_id=user_id,
        posted_at=date(2025, month, 3),
        merchant="Synthetic",
        amount=Decimal(amount),
        currency=currency,
        category=category,
    )
    db.add(row)
    db.flush()
    return row


def test_mixed_currency_requires_selection(ledger):
    db, user_id = ledger
    add_row(db, user_id, "-10.00")
    add_row(db, user_id, "-20.00", currency="USD")
    repo = TransactionRepository(db)
    with pytest.raises(ValueError, match="currency"):
        repo.monthly_summary(user_id, "2025-01")
    assert repo.monthly_summary(user_id, "2025-01", currency="EUR")["spending"] == Decimal(10)


def test_breakdown_preserves_cash_flow_and_traces_explicit_rules(ledger):
    db, user_id = ledger
    expense = add_row(db, user_id, "-100.00")
    duplicate = add_row(db, user_id, "-100.00")
    refund = add_row(db, user_id, "30.00", "Refund:Groceries")
    transfer = add_row(db, user_id, "-200.00", "Internal Transfer")
    add_row(db, user_id, "1000.00", "Income")
    service = FinanceAnalyticsService(TransactionRepository(db))
    report = service.get_spending_report(user_id, "2025-01", "EUR")
    assert report["income"] == "1030.00"
    assert report["spending"] == "400.00"
    assert report["net_cash_flow"] == "630.00"
    assert report["net_spending"] == "170.00"
    assert report["categories"]["Groceries"] == "170.00"
    assert report["suspected_duplicate_ids"] == sorted([str(expense.id), str(duplicate.id)])
    fact = next(f for f in report["_evidence"]["facts"] if f["key"] == "net_spending")
    assert set(fact["transaction_ids"]) == {str(expense.id), str(duplicate.id), str(refund.id)}
    assert str(transfer.id) not in fact["transaction_ids"]


@pytest.mark.parametrize("parser", [IngestionService, DocumentIngestionService])
def test_csv_preserves_currency_and_rejects_invalid_money(parser):
    service = parser()
    rows = service.parse_csv(b"date,merchant,amount,currency\n2025-01-01,Example,-1.20,EUR\n")
    assert rows[0].currency == "EUR"
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        service.parse_csv(b"date,merchant,amount,currency\n2025-01-01,Example,1.001,EUR\n")
    assert exc.value.status_code == 400


def test_reviewer_rejects_unsupported_free_text():
    state = ReviewerAgent().run(
        {
            "tool_results": {"income": "100.00"},
            "agent_outputs": {"orchestrator": "Your income is EUR 9999."},
        }
    )
    assert state["review_status"] == "rejected"
    assert "9999" not in state["final_answer"]


@pytest.mark.parametrize("amount", ["1.001", "10000000000.00", "NaN", "Infinity"])
def test_rejects_unrepresentable_money(amount):
    with pytest.raises(ValidationError):
        TransactionCreate(posted_at=date(2025, 1, 1), merchant="Synthetic", amount=amount)


def test_currency_is_normalized():
    item = TransactionCreate(
        posted_at=date(2025, 1, 1), merchant="Synthetic", amount=Decimal("-1.20"), currency="eur"
    )
    assert item.currency == "EUR"


def test_monthly_comparison_reconciles_category_contributions(ledger):
    db, user_id = ledger
    add_row(db, user_id, "-100.00", "Groceries", month=1)
    add_row(db, user_id, "-50.00", "Subscriptions", month=1)
    add_row(db, user_id, "-210.00", "Groceries", month=2)
    add_row(db, user_id, "-180.00", "Subscriptions", month=2)
    service = FinanceAnalyticsService(TransactionRepository(db))
    report = service.compare_spending(user_id, "2025-01", "2025-02", "EUR")
    assert report["net_spending_delta"] == "240.00"
    facts = {f["key"]: f for f in report["_evidence"]["facts"]}
    assert facts["delta:category:Groceries"]["amount"] == "110.00"
    assert facts["delta:category:Subscriptions"]["amount"] == "130.00"
    assert len(facts["delta:net_spending"]["transaction_ids"]) == 4
    assert len(facts["delta:category:Groceries"]["left_transaction_ids"]) == 1
    assert len(facts["delta:category:Groceries"]["right_transaction_ids"]) == 1


def test_comparison_never_compares_two_different_currencies(ledger):
    db, user_id = ledger
    add_row(db, user_id, "-10.00", month=1)
    add_row(db, user_id, "-20.00", currency="USD", month=2)
    service = FinanceAnalyticsService(TransactionRepository(db))
    for compare in (service.compare_months, service.compare_spending):
        with pytest.raises(ValueError, match="currency"):
            compare(user_id, "2025-01", "2025-02")


def test_real_tools_produce_grounded_explanations_from_one_snapshot(ledger):
    from app.agents.tools import FinanceToolLayer
    from app.services.financial_review import review_financial_draft

    db, user_id = ledger
    for _ in range(12):
        add_row(db, user_id, "-10.00")
    add_row(db, user_id, "-2000.00", "Shopping")
    add_row(db, user_id, "100.00", "Income")
    tools = FinanceToolLayer(FinanceAnalyticsService(TransactionRepository(db)))
    tools.configure_context("2025-01", "EUR")
    for method in (
        tools.detect_anomalies,
        tools.get_recurring_payments,
        tools.generate_budget,
        tools.get_top_merchants,
        tools.get_spending_by_category,
    ):
        result = method(user_id)
        status, _, answer = review_financial_draft(result, "Unsupported USD 9999")
        assert status == "accepted" and "9999" not in answer and "EUR" in answer
        assert result["_evidence"]["facts"]
        assert all(f["transaction_ids"] for f in result["_evidence"]["facts"])
    assert "id" in tools.get_transactions(user_id)["transactions"][0]


def test_refunds_do_not_change_gross_income_and_can_exceed_spending(ledger):
    db, user_id = ledger
    add_row(db, user_id, "50.00", "Refund:Groceries")
    report = FinanceAnalyticsService(TransactionRepository(db)).get_spending_report(
        user_id, "2025-01"
    )
    assert report["income"] == "50.00" and report["spending"] == "0.00"
    assert report["net_spending"] == "-50.00"


@pytest.mark.parametrize("code", ["12A", "EU€", "EU", "EURO", " EUR"])
def test_invalid_currency_codes(code):
    with pytest.raises(ValidationError):
        TransactionCreate(
            posted_at=date(2025, 1, 1), merchant="Synthetic", amount="1", currency=code
        )


def test_existing_analytics_keep_gross_semantics_and_currency_scope(ledger):
    db, user_id = ledger
    add_row(db, user_id, "-100.00")
    repo = TransactionRepository(db)
    service = FinanceAnalyticsService(repo)
    assert repo.spending_by_category(user_id, "2025-01") == {"Groceries": Decimal("100.00")}
    assert repo.top_merchants(user_id) == {"Synthetic": Decimal("100.00")}
    assert service.generate_budget(user_id) == {"Groceries": Decimal("33.33")}
    result = service.compare_months(user_id, "2025-01", "2025-02")
    assert result["spending_delta"] == Decimal("-100.00")
    assert result["left"]["currency"] == "EUR" == result["right"]["currency"]
    with pytest.raises(ValueError, match="currency"):
        repo.rows_for_analysis(user_id, currency="12A")
