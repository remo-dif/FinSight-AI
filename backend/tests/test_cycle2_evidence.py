import copy
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.financial_evidence import comparison_report, spending_report
from app.services.financial_review import review_financial_draft


def report(month="2025-01", amount="-10.00"):
    row = SimpleNamespace(id=uuid4(), posted_at=date.fromisoformat(month + "-01"),
                          merchant="Synthetic", description="", amount=Decimal(amount),
                          currency="EUR", category="Groceries")
    return spending_report([row], "EUR", month)


@pytest.mark.parametrize("mutation", ["fact_amount", "total", "category", "cash_flow", "missing_fact", "duplicate_refs"])
def test_inconsistent_report_is_rejected_not_rendered(mutation):
    data = report()
    if mutation == "fact_amount": data["_evidence"]["facts"][1]["amount"] = "9999.00"
    if mutation == "total": data["spending"] = "9999.00"
    if mutation == "category": data["categories"]["Groceries"] = "9999.00"
    if mutation == "cash_flow":
        data["net_cash_flow"] = "9999.00"
        next(f for f in data["_evidence"]["facts"] if f["key"] == "net_cash_flow")["amount"] = "9999.00"
    if mutation == "missing_fact": data["_evidence"]["facts"].pop()
    if mutation == "duplicate_refs": data["_evidence"]["facts"][1]["transaction_ids"] *= 2
    status, _, answer = review_financial_draft(data, "invalid draft")
    assert status == "rejected"
    assert "9999" not in answer


@pytest.mark.parametrize("mutation", ["delta", "left_total", "left_refs"])
def test_comparison_rejects_inconsistent_values_and_reference_sides(mutation):
    data = comparison_report(report(), report("2025-02", "-20.00"))
    if mutation == "delta": data["spending_delta"] = "9999.00"
    if mutation == "left_total": data["left"]["spending"] = "9999.00"
    if mutation == "left_refs": data["_evidence"]["facts"][0]["left_transaction_ids"] = []
    assert review_financial_draft(data, "invalid")[0] == "rejected"


def test_valid_snapshot_and_safe_fallback():
    data = report()
    before = copy.deepcopy(data)
    status, review, answer = review_financial_draft(data, "Invent a different total")
    assert status == "accepted" and "replaced" in review
    assert "EUR 10.00" in answer and data == before


def test_reviewer_binds_values_and_ids_to_the_canonical_tool_snapshot(monkeypatch):
    from app.agents.orchestrator import OrchestratorAgent
    from app.agents.tools import FinanceToolLayer
    from tests.test_financial_correctness import ledger  # noqa: F401
    from app.services.analytics import FinanceAnalyticsService
    from app.repositories.transactions import TransactionRepository
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.core.database import Base
    from app.models.user import User
    from app.models.finance import Transaction

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    uid = uuid4()
    with Session(engine) as db:
        db.add(User(id=uid, email="canonical@example.invalid", full_name="Synthetic", password_hash="unused"))
        db.add(Transaction(user_id=uid, posted_at=date(2025, 1, 1), merchant="Synthetic",
                           amount=Decimal("-10.00"), currency="EUR", category="Groceries"))
        db.flush()
        class Rag:
            def retrieve_chunks(self, *args, **kwargs): return []
        class MutatingLLM:
            def synthesize_financial_answer(self, message, intent, results, chunks):
                # Even internally consistent tampering must not replace the original calculation.
                results["spending"] = "9999.00"
                results["net_cash_flow"] = "-9999.00"
                results["net_spending"] = "9999.00"
                results["categories"]["Groceries"] = "9999.00"
                for fact in results["_evidence"]["facts"]:
                    if fact["key"] in {"spending", "net_spending", "category:Groceries"}: fact["amount"] = "9999.00"
                    if fact["key"] == "net_cash_flow": fact["amount"] = "-9999.00"
                return json.dumps({"claim_ids": [f["key"] for f in results["_evidence"]["facts"]]})
        tools = FinanceToolLayer(FinanceAnalyticsService(TransactionRepository(db)))
        state = OrchestratorAgent(tools, Rag(), MutatingLLM()).run({"user_id": uid, "message": "summary 2025-01", "currency": "EUR"})
        assert state["review_status"] == "rejected"
        assert "9999" not in state["final_answer"]
    engine.dispose()
