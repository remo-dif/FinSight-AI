import json
from datetime import date
from typing import Any, Callable

from langgraph.graph import END, StateGraph

from app.agents.state import AgentIntent, AgentState
from app.agents.tools import FinanceToolLayer
from app.services.llm import LLMService
from app.services.rag import RagService


ToolRunner = Callable[["OrchestratorAgent", AgentState], dict[str, Any]]


class OrchestratorAgent:
    _compiled_graph: Any | None = None

    def __init__(self, tools: FinanceToolLayer, rag_service: RagService, llm_service: LLMService) -> None:
        self.tools = tools
        self.rag_service = rag_service
        self.llm_service = llm_service
        self.graph = self._get_compiled_graph()

    @classmethod
    def _get_compiled_graph(cls):
        if cls._compiled_graph is None:
            cls._compiled_graph = cls._build_graph()
        return cls._compiled_graph

    @classmethod
    def _build_graph(cls):
        workflow = StateGraph(AgentState)
        workflow.add_node("supervisor", cls._supervisor_node)
        workflow.add_node("anomaly_specialist", cls._tool_node(cls._run_anomaly))
        workflow.add_node("recurring_specialist", cls._tool_node(cls._run_recurring))
        workflow.add_node("budget_specialist", cls._tool_node(cls._run_budget))
        workflow.add_node("merchant_specialist", cls._tool_node(cls._run_merchant))
        workflow.add_node("category_specialist", cls._tool_node(cls._run_category))
        workflow.add_node("summary_specialist", cls._tool_node(cls._run_summary))
        workflow.add_node("reviewer", ReviewerAgent().run)

        workflow.set_entry_point("supervisor")
        workflow.add_conditional_edges(
            "supervisor",
            cls._select_specialist,
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
        state["_agent"] = self
        state["rag_results"] = self.rag_service.retrieve_chunks(state["user_id"], state["message"], limit=5)
        return self.graph.invoke(state)

    @staticmethod
    def _supervisor_node(state: AgentState) -> AgentState:
        return {"intent": state["_agent"].route(state["message"])}

    @staticmethod
    def _select_specialist(state: AgentState) -> AgentIntent:
        return state.get("intent", "summary")

    @staticmethod
    def _tool_node(runner: ToolRunner) -> Callable[[AgentState], AgentState]:
        def node(state: AgentState) -> AgentState:
            agent = state["_agent"]
            tool_results = runner(agent, state)
            agent_output = agent._synthesize_answer(state["intent"], state, tool_results)
            return {
                "tool_results": tool_results,
                "agent_outputs": {"orchestrator": agent_output},
            }

        return node

    def _synthesize_answer(self, intent: AgentIntent, state: AgentState, tool_results: dict[str, Any]) -> str:
        rag_chunks = []
        for chunk in state.get("rag_results", []):
            if hasattr(chunk, "__dict__"):
                rag_chunks.append(chunk.__dict__)
            else:
                rag_chunks.append(chunk)

        result = self.llm_service.synthesize_financial_answer(
            state["message"],
            intent,
            tool_results,
            rag_chunks,
        )
        if result:
            return result
        return self._answer_for_intent(intent, tool_results)

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

    def _answer_for_intent(self, intent: AgentIntent, tool_results: dict[str, Any]) -> str:
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
        fallback = answers[intent]
        summary = tool_results.get("summary")
        if intent == "summary" and summary is not None:
            return f"Your {month} summary is: {json.dumps(summary, default=str)}"
        return fallback


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
