from dataclasses import asdict

import pytest

from evaluation.answer_metrics import (
    SAFE_ABSTENTIONS,
    aggregate,
    grade_authorization,
    grade_conflict_draft,
    grade_response,
)
from evaluation.answer_rubric import load_answer_rubric
from evaluation.schemas import load_document_dataset

BUNDLE = load_document_dataset()
RUBRICS = {case.id: case for case in load_answer_rubric(BUNDLE).cases}
PASSAGES = {
    ("account-january", "closing"): (10, 20),
    ("account-january", "movements"): (0, 10),
    ("expenses-january", "breakdown"): (0, 10),
}
VERIFIED = {
    "closing": ("account-january", (0, 20)),
    "distractor": ("distractor-usd", (0, 20)),
    "payments": ("account-january", (0, 10)),
    "expenses": ("expenses-january", (0, 10)),
}
CORRECT = "closing-balance: 1,350.00 EUR @ 2025-01"


def grade(case, answer, citations=("closing",), status="ok"):
    return grade_response(
        RUBRICS[case],
        {
            "status": status,
            "answer": answer,
            "abstained": status != "ok",
            "citations": [{"reference": ref} for ref in citations],
        },
        VERIFIED,
        PASSAGES,
    )


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (CORRECT, "pass"),
        ("closing-balance: 1350 EUR @ 2025-01", "pass"),
        (CORRECT.replace("EUR", "USD"), "fail"),
        (CORRECT.replace("2025-01", "2025-02"), "fail"),
        (CORRECT.replace(": ", ": not "), "fail"),
        (CORRECT + "\ninterest: 50.00 EUR @ 2025-01", "fail"),
        (CORRECT + "\nunclear prose", "needs_review"),
        ("unclear prose\nclosing-balance: 100 EUR @ 2025-01", "fail"),
        ("The month ended with about thirteen hundred.", "needs_review"),
    ],
)
def test_controlled_facts(answer, expected):
    assert grade("Q09", answer).status == expected


def test_required_fact_missing():
    result = grade("Q01", CORRECT)
    assert result.status == "fail"
    assert result.metrics["required_fact_completeness"] == 0.5


def test_valid_citation_does_not_prove_truth_or_relevance():
    wrong = grade("Q09", "closing-balance: 1600 EUR @ 2025-01")
    irrelevant = grade("Q09", CORRECT, ("distractor",))
    assert wrong.metrics["citation_validity"] == irrelevant.metrics["citation_validity"] == 1
    assert wrong.metrics["answer_correctness"] == 0
    assert irrelevant.metrics["answer_correctness"] == 1
    assert wrong.metrics["claim_support"] == irrelevant.metrics["claim_support"] == 0


def test_cross_document_support_and_duplicate_citations():
    answer = "payments-equal-expenses: 250 = 250 EUR @ 2025-01"
    incomplete = grade("Q04", answer, ("payments",))
    complete = grade("Q04", answer, ("payments", "expenses", "expenses", "distractor"))
    assert incomplete.metrics["citation_completeness"] == 0
    assert complete.metrics["claim_support"] == 1
    assert complete.metrics["citation_precision"] == pytest.approx(2 / 3)


@pytest.mark.parametrize("reference", ["invalid", "persisted-but-not-in-prompt"])
def test_unverified_reference(reference):
    result = grade("Q09", CORRECT, ("closing", reference))
    assert result.status == "fail"
    assert result.metrics["citation_validity"] == 0.5


def test_abstention_and_error_are_distinct():
    safe = min(SAFE_ABSTENTIONS)
    assert grade("Q06", safe, (), "abstained").status == "pass"
    assert grade("Q06", safe + " Actuals were EUR 350.", (), "abstained").status == "fail"
    assert grade("Q06", safe, (), "provider_error").status == "execution_error"
    assert grade("Q06", safe, (), None).status == "execution_error"


def test_conflict_draft_requires_both_values_without_arbitrary_choice():
    rubric = RUBRICS["Q08"]
    draft = "plan: 300 EUR @ 2025-02\ndraft: 350 EUR @ 2025-02\nauthoritative-value-exists: false"
    assert grade_conflict_draft(rubric, draft, True) == "pass"
    assert grade_conflict_draft(rubric, draft.splitlines()[0], False) == "fail"
    assert grade_conflict_draft(rubric, draft + "\napproved: 325 EUR @ 2025-02", True) == "fail"


def test_authorization_checks_entire_body_and_calls():
    assert grade_authorization(404, {"detail": "Document not found"}, False, False).status == "pass"
    assert grade_authorization(404, {"detail": "private-plan"}, False, False).status == "fail"
    assert grade_authorization(404, {"detail": "Document not found"}, True, False).status == "fail"


def test_partial_population_produces_null_aggregate():
    row = {"grade": asdict(grade("Q09", CORRECT)), "applicable_metrics": ["answer_correctness"]}
    assert aggregate([row], 1)["metrics"]["answer_correctness"]["mean"] == 1
    assert aggregate([row], 2)["metrics"]["answer_correctness"]["mean"] is None


def test_passage_split_across_cited_chunks_uses_union_not_sum():
    response = {
        "status": "ok",
        "answer": CORRECT,
        "abstained": False,
        "citations": [{"reference": "left"}, {"reference": "right"}],
    }
    rubric = RUBRICS["Q09"]
    spans = {"left": ("account-january", (8, 16)), "right": ("account-january", (13, 20))}
    assert grade_response(rubric, response, spans, PASSAGES).metrics["claim_support"] == 1
    spans["right"] = ("account-january", (13, 19))
    assert grade_response(rubric, response, spans, PASSAGES).metrics["claim_support"] == 0


def test_refund_and_transfer_polarity_are_independent():
    refs = {"policy": ("expenses-january", (0, 10))}
    passages = {("expenses-january", "refund-policy"): (0, 10)}
    response = {
        "status": "ok",
        "answer": "includes-refunds: false\nincludes-transfers: true",
        "abstained": False,
        "citations": [{"reference": "policy"}],
    }
    result = grade_response(RUBRICS["Q13"], response, refs, passages)
    assert result.status == "fail"
    assert result.metrics["required_fact_completeness"] == 0.5


def test_unknown_prose_leaves_semantic_metrics_null():
    result = grade("Q09", CORRECT + "\nThere might be additional details.")
    assert result.status == "needs_review"
    assert result.metrics["answer_correctness"] is None
    assert result.metrics["citation_completeness"] is None
    assert result.metrics["citation_validity"] == 1


Q05_AMOUNTS = (
    "recognized-revenue: 800 EUR @ 2025-01\n"
    "uncollected-revenue: 200 EUR @ 2025-01\n"
    "cash-receipts: 600 EUR @ 2025-01"
)
Q05_RELATIONSHIP = "\nrevenue-cash-relationship: uncollected-revenue explains revenue-cash-gap"


@pytest.mark.parametrize(
    ("explanation", "include_terminology", "status", "correctness", "completeness", "support"),
    [
        ("", True, "fail", 0, 0.75, 1),
        (Q05_RELATIONSHIP, True, "pass", 1, 1, 1),
        (
            Q05_RELATIONSHIP.replace("uncollected-revenue", "foreign-exchange"),
            True,
            "fail",
            0,
            0.75,
            0.75,
        ),
        (Q05_RELATIONSHIP, False, "fail", 1, 1, 0.75),
        (
            "\nThe figures differ because part of the revenue is unpaid.",
            True,
            "needs_review",
            None,
            None,
            None,
        ),
    ],
)
def test_q05_requires_causality_and_complete_evidence(
    explanation, include_terminology, status, correctness, completeness, support
):
    document = "revenue-january"
    passages = {
        (document, "recognized"): (0, 10),
        (document, "cash"): (10, 20),
        (document, "terminology"): (20, 30),
    }
    spans = {"revenue": (document, (0, 30 if include_terminology else 20))}
    result = grade_response(
        RUBRICS["Q05"],
        {
            "status": "ok",
            "answer": Q05_AMOUNTS + explanation,
            "abstained": False,
            "citations": [{"reference": "revenue"}],
        },
        spans,
        passages,
    )
    assert result.status == status
    assert result.metrics["answer_correctness"] == correctness
    assert result.metrics["required_fact_completeness"] == completeness
    assert result.metrics["claim_support"] == support
    assert result.metrics["citation_validity"] == 1
