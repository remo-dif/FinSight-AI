from uuid import uuid4

from app.agents.orchestrator import OrchestratorAgent


def grounded(values, label="budget", period="all history"):
    return {
        **values,
        "_evidence": {
            "currency": "EUR",
            "period": period,
            "source_transaction_ids": ["synthetic-transaction"],
            "facts": [
                {
                    "key": label,
                    "label": label,
                    "amount": "500.00",
                    "currency": "EUR",
                    "period": period,
                    "transaction_ids": ["synthetic-transaction"],
                }
            ],
        },
    }


class FakeTools:
    def configure_context(self, month, currency):
        self.month = month

    def detect_anomalies(self, user_id):
        return grounded({"anomalies": []}, "anomaly")

    def get_recurring_payments(self, user_id):
        return grounded({"recurring": []}, "recurring")

    def generate_budget(self, user_id):
        return grounded({"Groceries": "500.00"})

    def get_top_merchants(self, user_id):
        return grounded({"Rent": "1500.00"}, "merchant")

    def get_spending_by_category(self, user_id):
        return grounded({"Housing": "1500.00"}, "category", self.month)

    def get_monthly_summary(self, user_id, month):
        return grounded(
            {
                "month": month,
                "income": "4000.00",
                "spending": "1505.00",
                "net_cash_flow": "2495.00",
            },
            "summary",
            month,
        )


class FakeRag:
    def retrieve_chunks(self, user_id, query, limit=5):
        return []


class FakeLLM:
    def synthesize_financial_answer(self, user_message, intent, tool_results, rag_chunks):
        return f"{intent}: {tool_results}"


def test_orchestrator_routes_budget_to_budget_tool():
    state = OrchestratorAgent(FakeTools(), FakeRag(), FakeLLM()).run(
        {"user_id": uuid4(), "message": "make a budget"}
    )
    assert state["intent"] == "budget"
    assert state["review"].startswith("Accepted")
    assert "budget" in state["final_answer"].lower()


def test_orchestrator_covers_core_intents():
    agent = OrchestratorAgent(FakeTools(), FakeRag(), FakeLLM())

    cases = {
        "anything unusual?": "anomaly",
        "show recurring subscriptions": "recurring",
        "top merchants": "merchant",
        "spending by category": "category",
        "what is my month looking like?": "summary",
    }

    for message, expected in cases.items():
        state = agent.run({"user_id": uuid4(), "message": message})
        assert state["intent"] == expected
        assert state["review_status"] == "accepted"
