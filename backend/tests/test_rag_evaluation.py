import copy

import pytest

from evaluation.runner import evaluate, evaluate_case, grade_case, load_dataset, stable_id


@pytest.mark.parametrize("case", load_dataset()["cases"], ids=lambda case: case["id"])
def test_supported_baseline_and_security_gates(case):
    result = evaluate_case(load_dataset(), case)
    assert result["status"] != "failed", result
    assert result["answer_quality_evaluated"] == (case.get("capability") != "document_qa")


def test_grader_rejects_wrong_expected_amount_instead_of_reusing_analytics():
    dataset = load_dataset()
    case = copy.deepcopy(dataset["cases"][0])
    case["expected_claims"]["spending"]["amount"] = "999.00"
    assert "unsupported_annotated_claim:spending" in evaluate_case(dataset, case)["failure_reasons"]


def test_grader_rejects_wrong_source_reference():
    dataset = load_dataset()
    case = copy.deepcopy(dataset["cases"][0])
    case["expected_claims"]["spending"]["records"] = ["salary"]
    assert "unsupported_annotated_claim:spending" in evaluate_case(dataset, case)["failure_reasons"]


def test_dataset_reproducible_without_provider_calls_or_fake_semantic_scores():
    first, second = evaluate(), evaluate()
    assert first == second
    assert first["total"] == 18
    assert first["partial"] > 0
    assert first["semantic_faithfulness"] is None
    assert first["document_citation_correctness"] is None


def test_grader_rejects_foreign_context_even_if_no_secret_was_echoed():
    from app.services.rag import RagChunkResult

    dataset = load_dataset()
    case = next(case for case in dataset["cases"] if case["id"] == "R11-foreign-records-excluded")
    foreign = RagChunkResult(
        "not echoed", {"source": {"id": str(stable_id("document", "private"))}}
    )
    state = {
        "final_answer": "No matching financial facts",
        "rag_results": [foreign],
        "tool_results": {"_evidence": {"facts": [], "source_transaction_ids": []}},
    }
    result = grade_case(dataset, case, state, [foreign], [])
    assert "unauthorized_document_in_retrieval_or_context" in result["failure_reasons"]
    assert result["status"] == "failed"


def test_cli_fails_visible_incomplete_capabilities_in_strict_mode(monkeypatch, capsys):
    from evaluation import runner

    monkeypatch.setattr("sys.argv", ["evaluation.runner", "--require-complete"])
    assert runner.main() == 1
    captured = capsys.readouterr()
    assert '"partial": 3' in captured.out
    assert "partial" in captured.err


def test_cli_returns_nonzero_for_failed_cases(monkeypatch, capsys):
    from evaluation import runner

    monkeypatch.setattr("sys.argv", ["evaluation.runner"])
    monkeypatch.setattr(
        runner,
        "evaluate",
        lambda: {
            "total": 1,
            "passed": 0,
            "failed": 1,
            "partial": 0,
            "cases": [{"id": "synthetic-failure", "failure_reasons": ["wrong_amount"]}],
        },
    )
    assert runner.main() == 1
    assert "wrong_amount" in capsys.readouterr().out
