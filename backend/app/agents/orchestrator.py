from datetime import date
from typing import Callable

from langgraph.graph import END, StateGraph

from app.agents.state import AgentIntent, AgentState
from app.agents.tools import FinanceToolLayer


ToolRunner = Callable[[AgentState], dict]


class OrchestratorAgent:
    def __init__(self, tools: FinanceToolLayer) -> None:
        self.tools = tools
        self.graph = self._build_graph()

    def route(self, message: str) -> AgentIntent:
        lower = message.lower()
        if "anomal" in lower or "unusual" in lower:
            return "anomaly"
        if "recurring" in lower or "subscription" in lower:
            return "recurring"
        if "budget" in lower:
            return "budget"
        if "merchant" in lower or "top" in lower:
            return "merchant"
        if "category" in lower or "spending" in lower:
            return "category"
        return "summary"

    def run(self, state: AgentState) -> AgentState:
        return self.graph.invoke(state)

    def _build_graph(self):
        workflow = StateGraph(AgentState)
        workflow.add_node("supervisor", self._supervisor)
        workflow.add_node("anomaly_specialist", self._tool_node(self._run_anomaly))
        workflow.add_node("recurring_specialist", self._tool_node(self._run_recurring))
        workflow.add_node("budget_specialist", self._tool_node(self._run_budget))
        workflow.add_node("merchant_specialist", self._tool_node(self._run_merchant))
        workflow.add_node("category_specialist", self._tool_node(self._run_category))
        workflow.add_node("summary_specialist", self._tool_node(self._run_summary))
        workflow.add_node("reviewer", ReviewerAgent().run)

        workflow.set_entry_point("supervisor")
        workflow.add_conditional_edges(
            "supervisor",
            self._select_specialist,
            {
                "anomaly": "anomaly_specialist",
                "recurring": "recurring_specialist",
                "budget": "budget_specialist",
                "merchant": "merchant_specialist",
                "category": "category_specialist",
                "summary": "summary_specialist",
            },
        )
        for node in (
            "anomaly_specialist",
            "recurring_specialist",
            "budget_specialist",
            "merchant_specialist",
            "category_specialist",
            "summary_specialist",
        ):
            workflow.add_edge(node, "reviewer")
        workflow.add_edge("reviewer", END)
        return workflow.compile()

    def _supervisor(self, state: AgentState) -> AgentState:
        return {"intent": self.route(state["message"])}

    def _select_specialist(self, state: AgentState) -> AgentIntent:
        return state.get("intent", "summary")

    def _tool_node(self, runner: ToolRunner) -> Callable[[AgentState], AgentState]:
        def node(state: AgentState) -> AgentState:
            tool_results = runner(state)
            return {
                "tool_results": tool_results,
                "agent_outputs": {"orchestrator": self._answer_for_intent(state["intent"])},
            }

        return node

    def _run_anomaly(self, state: AgentState) -> dict:
        return self.tools.detect_anomalies(state["user_id"])

    def _run_recurring(self, state: AgentState) -> dict:
        return self.tools.get_recurring_payments(state["user_id"])

    def _run_budget(self, state: AgentState) -> dict:
        return self.tools.generate_budget(state["user_id"])

    def _run_merchant(self, state: AgentState) -> dict:
        return self.tools.get_top_merchants(state["user_id"])

    def _run_category(self, state: AgentState) -> dict:
        return self.tools.get_spending_by_category(state["user_id"])

    def _run_summary(self, state: AgentState) -> dict:
        month = date.today().strftime("%Y-%m")
        return self.tools.get_monthly_summary(state["user_id"], month)

    def _answer_for_intent(self, intent: AgentIntent) -> str:
        month = date.today().strftime("%Y-%m")
        answers = {
            "anomaly": (
                "I reviewed your recent spending and flagged the transactions that stand out "
                "statistically."
            ),
            "recurring": (
                "I found merchants with repeated charges and estimated their cadence and confidence."
            ),
            "budget": "I generated category budget targets from your historical spending.",
            "merchant": "Here are the merchants contributing most to your spending.",
            "category": "Here is your spending grouped by category.",
            "summary": f"Here is your month-to-date summary for {month}.",
        }
        return answers[intent]


class ReviewerAgent:
    def run(self, state: AgentState) -> AgentState:
        if not state.get("tool_results"):
            state["review_status"] = "rejected"
            state["review"] = "Rejected: response lacks tool-grounded financial data."
            state["final_answer"] = "I need transaction data before I can answer that safely."
            return state
        state["review_status"] = "accepted"
        state["review"] = "Accepted: response is grounded in approved tool output."
        state["final_answer"] = state["agent_outputs"]["orchestrator"]
        return state
