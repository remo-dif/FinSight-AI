from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.agents.orchestrator import ReviewerAgent
from app.api.routes.chat import chat
from app.models.finance import Transaction
from app.schemas.chat import ChatRequest
from tests import test_chat_lifecycle as chat_fixtures
from tests.test_financial_review import evidence

chat_db = chat_fixtures.chat_db
install_providers = chat_fixtures.install_providers


@pytest.mark.parametrize(
    "message,currency,hint",
    [
        ("summary SEK 2025-01", None, "currency"),
        ("summary XYZ 2025-01", None, "currency"),
        ("summary 2025-01", "XYZ", "currency"),
        ("summary in xyz 2025-01", None, "currency"),
        ("summary last month", None, "YYYY-MM"),
        ("summary January 2025", None, "YYYY-MM"),
        ("summary 2025-01-15", None, "YYYY-MM"),
        ("summary for 2025", None, "YYYY-MM"),
        ("budget 2025-01", None, "all history"),
        ("recurring payments 2025-01", None, "all history"),
        ("compare merchants 2025-01 2025-02", None, "comparison"),
        ("compare spending", None, "two"),
    ],
)
def test_invalid_context_is_actionable_and_precedes_providers(
    chat_db, monkeypatch, message, currency, hint
):
    db, user = chat_db
    calls = install_providers(monkeypatch, db)
    with pytest.raises(HTTPException) as exc:
        chat(ChatRequest(message=message, currency=currency), user, db)
    assert exc.value.status_code == 422
    assert hint.lower() in str(exc.value.detail).lower()
    assert calls == []


def test_requested_merchant_month_is_applied(chat_db, monkeypatch):
    db, user = chat_db
    for month, value in [(1, "-10.00"), (2, "-100.00")]:
        db.add(
            Transaction(
                user_id=user.id,
                posted_at=date(2025, month, 1),
                merchant="Synthetic",
                amount=Decimal(value),
                currency="EUR",
                category="Groceries",
            )
        )
    db.commit()
    install_providers(monkeypatch, db)
    result = chat(ChatRequest(message="top merchants 2025-01", currency="EUR"), user, db)
    assert result.tool_results["Synthetic"] == "10.00"
    assert result.tool_results["_evidence"]["period"] == "2025-01"


@pytest.mark.parametrize("intent", ["merchant", "anomaly", "recurring", "budget"])
def test_reviewer_enforces_resolved_period_for_every_intent(intent):
    result = ReviewerAgent().run(
        {
            "intent": intent,
            "reporting_period": "2025-02",
            "currency": "EUR",
            "tool_results": evidence(),
            "agent_outputs": {"orchestrator": '{"claim_ids":["spending"]}'},
        }
    )
    assert result["review_status"] == "rejected"


@pytest.mark.parametrize(
    "message",
    [
        "summary xyz 2025-01",
        "summary currency=xyz",
        "summary Q1",
        "summary past month",
        "spending from 2025-01 to 2025-03",
    ],
)
def test_unsupported_context_forms_are_not_silently_defaulted(message):
    from app.services.financial_context import resolve_context

    with pytest.raises(ValueError):
        resolve_context(message, "summary")


@pytest.mark.parametrize(
    "message,intent", [("budget using all history", "budget"), ("may I see my summary?", "summary")]
)
def test_ordinary_words_are_not_misidentified_as_currency_or_period(message, intent):
    from app.services.financial_context import resolve_context

    assert resolve_context(message, intent)["intent"] == intent


@pytest.mark.parametrize("message", ["summary Jan", "summary in jan", "summary JAN"])
def test_abbreviated_months_produce_an_actionable_period_error(message):
    from app.services.financial_context import resolve_context

    with pytest.raises(ValueError, match="YYYY-MM"):
        resolve_context(message, "summary")
