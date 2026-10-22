import json

import pytest

from app.services.financial_review import review_financial_draft


def evidence():
    return {
        "_evidence": {
            "currency": "EUR",
            "period": "2025-01",
            "source_transaction_ids": ["synthetic-transaction"],
            "facts": [
                {
                    "key": "spending",
                    "label": "Gross spending",
                    "amount": "123.45",
                    "currency": "EUR",
                    "period": "2025-01",
                    "transaction_ids": ["synthetic-transaction"],
                }
            ],
        }
    }


@pytest.mark.parametrize(
    "draft",
    [
        "You spent USD 9999 in 2030-01.",
        '{"claim_ids":["invented"]}',
        '{"claim_ids":["spending"],"amount":"9999"}',
        '{"claim_ids":[]}',
        '{"claim_ids":["spending"],"transaction_ids":["other-user"]}',
        "null",
        "[]",
    ],
)
def test_invented_claims_use_verified_fallback(draft):
    status, review, answer = review_financial_draft(evidence(), draft)
    assert status == "accepted"
    assert "replaced" in review
    assert answer == "Gross spending: EUR 123.45 (2025-01)."


def test_valid_claims_and_empty_result():
    status, review, answer = review_financial_draft(evidence(), '{"claim_ids":["spending"]}')
    assert status == "accepted" and "replaced" not in review
    assert "EUR 123.45" in answer
    data = evidence()
    data["_evidence"]["facts"] = []
    assert "No matching" in review_financial_draft(data, '{"claim_ids":[]}')[2]


@pytest.mark.parametrize(
    "field,value",
    [
        ("currency", "USD"),
        ("period", "2030-01"),
        ("amount", "NaN"),
        ("amount", "1.001"),
        ("transaction_ids", "invented"),
    ],
)
def test_inconsistent_evidence_is_rejected(field, value):
    data = evidence()
    data["_evidence"]["facts"][0][field] = value
    assert review_financial_draft(data, json.dumps({"claim_ids": ["spending"]}))[0] == "rejected"


def test_foreign_transaction_reference_is_rejected():
    data = evidence()
    data["_evidence"]["facts"][0]["transaction_ids"] = ["other-user-transaction"]
    assert review_financial_draft(data, '{"claim_ids":["spending"]}')[0] == "rejected"


@pytest.mark.parametrize("currency,months", [("USD", ["2025-01"]), ("EUR", ["2025-02"])])
def test_reviewer_rejects_mismatch_with_requested_context(currency, months):
    from app.agents.orchestrator import ReviewerAgent

    state = ReviewerAgent().run(
        {
            "tool_results": evidence(),
            "intent": "summary",
            "currency": currency,
            "months": months,
            "agent_outputs": {"orchestrator": '{"claim_ids":["spending"]}'},
        }
    )
    assert state["review_status"] == "rejected"
    assert "123.45" not in state["final_answer"]


@pytest.mark.parametrize("field,value", [("facts", "invalid"), ("source_transaction_ids", None)])
def test_malformed_evidence_is_rejected(field, value):
    data = evidence()
    data["_evidence"][field] = value
    assert review_financial_draft(data, '{"claim_ids":["spending"]}')[0] == "rejected"


def test_model_cannot_omit_an_existing_fact():
    data = evidence()
    data["_evidence"]["facts"].append({**data["_evidence"]["facts"][0], "key": "other"})
    status, review, answer = review_financial_draft(data, '{"claim_ids":["spending"]}')
    assert status == "accepted" and "replaced" in review
    assert answer.count("EUR 123.45") == 2
