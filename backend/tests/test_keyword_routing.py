"""Keyword routing must distinguish the request word ``top`` from embedded text."""

import pytest

from app.agents.orchestrator import OrchestratorAgent
from tests.test_orchestrator import FakeLLM, FakeRag, FakeTools


@pytest.fixture()
def agent():
    return OrchestratorAgent(FakeTools(), FakeRag(), FakeLLM())


@pytest.mark.parametrize(
    "message",
    [
        "top",
        "TOP",
        "ToP!",
        "Show my top expenses",
        "Which are the (top) payees?",
        "List top, please.",
        "My top-ranked expenses",
        "Show\ntop\tpayments",
    ],
)
def test_top_as_a_separate_word_routes_to_merchants(agent, message):
    assert agent.route(message) == "merchant"


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("I bought a laptop", "summary"),
        ("Show LAPTOP spending by category", "category"),
        ("Please stop", "summary"),
        ("How can I stop spending?", "category"),
        ("Desktop expenses", "summary"),
        ("Show desktop spending", "category"),
        ("Topping expenses", "summary"),
        ("Topological spending patterns", "category"),
        ("Expenses atop the statement", "summary"),
        ("top100", "summary"),
        ("top_score", "summary"),
        ("ÉtOP", "summary"),
    ],
)
def test_embedded_top_does_not_select_merchants(agent, message, intent):
    assert agent.route(message) == intent


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("top unusual expenses", "anomaly"),
        ("top recurring payments", "recurring"),
        ("top subscriptions", "recurring"),
        ("top budget targets", "budget"),
        ("top spending by category", "merchant"),
        ("laptop merchants", "merchant"),
        ("Show my merchants", "merchant"),
        ("Compare this month's spending", "summary"),
        ("Spending by category", "category"),
        ("How is my month?", "summary"),
    ],
)
def test_existing_intent_precedence_and_merchant_keyword_are_preserved(agent, message, intent):
    assert agent.route(message) == intent
