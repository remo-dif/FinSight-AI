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
        return {"month": month, "income": "4000.00"}


def test_orchestrator_routes_budget_to_budget_tool():
    state = OrchestratorAgent(FakeTools()).run({"user_id": uuid4(), "message": "make a budget"})
    assert state["intent"] == "budget"
    assert state["review"].startswith("Accepted")
    assert "budget" in state["final_answer"].lower()
