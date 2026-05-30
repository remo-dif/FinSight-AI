from uuid import uuid4

from app.agents.orchestrator import OrchestratorAgent


class FakeTools:
    def detect_anomalies(self, user_id):
        return {"anomalies": []}

    def get_recurring_payments(self, user_id):
        return {"recurring": []}

    def generate_budget(self, user_id):
        return {"Groceries": "500.00"}

    def get_top_merchants(self, user_id):
        return {"Rent": "1500.00"}

    def get_spending_by_category(self, user_id):
        return {"Housing": "1500.00"}

    def get_monthly_summary(self, user_id, month):
        return {"month": month, "income": "4000.00", "spending": "1505.00", "net_cash_flow": "2495.00"}


class FakeRag:
    def retrieve_chunks(self, user_id, query, limit=5):
        return []


class FakeLLM:
    def synthesize_financial_answer(self, user_message, intent, tool_results, rag_chunks):
        return f"{intent}: {tool_results}"


def test_orchestrator_routes_budget_to_budget_tool():
    state = OrchestratorAgent(FakeTools(), FakeRag(), FakeLLM()).run({"user_id": uuid4(), "message": "make a budget"})
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
