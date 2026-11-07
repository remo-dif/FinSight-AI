import copy
import json
import subprocess
from pathlib import Path

import pytest

from evaluation import baseline_suite
from evaluation.baseline_contract import (
    ContractError,
    load_json,
    normalize_report,
    parse_json,
    seal,
)
from evaluation.compare_baseline import compare, main

BASELINES = Path(__file__).parents[1] / "evaluation" / "baselines"


@pytest.fixture
def retrieval():
    return load_json(BASELINES / "retrieval_v1.json")


@pytest.fixture
def answer():
    return load_json(BASELINES / "answer_v1.json")


def signed(report):
    return seal({key: value for key, value in report.items() if key != "sha256"})


def row(report, key, scenario=None):
    return next(
        case for case in report["cases"] if case["id"] == key and case.get("scenario") == scenario
    )


def change_metric(report, key, name, value):
    metrics = row(report, key)["metrics"]
    # Eight retrieval cases in the reviewed corpus, each weighted 1/8.
    report["aggregates"]["retrieval"]["metrics"][name] += (value - metrics[name]) / 8
    metrics[name] = value


def set_single_hit(report, key, ranking):
    # Q01 and Q02 each have one relevant passage in one chunk, at k=5.
    metrics = (1, 1, 0.2, 0.2, 1) if ranking else (0, 0, 0, 0, 0)
    for name, value in zip(
        (
            "evidence_recall",
            "evidence_coverage",
            "chunk_precision",
            "novel_evidence_precision",
            "mrr",
        ),
        metrics,
        strict=True,
    ):
        change_metric(report, key, name, value)
    row(report, key)["diagnostics"] = {"ranking": ranking, "retrieved_count": len(ranking)}


def test_identical_reports_pass_and_git_provenance_is_not_a_gate(retrieval):
    assert compare(retrieval, retrieval)["exit_code"] == 0
    candidate = copy.deepcopy(retrieval)
    candidate["source"]["git_commit"] = "a" * 40
    candidate["source"]["working_tree_dirty"] = True
    assert compare(retrieval, signed(candidate))["differences"] == []


def test_case_order_and_object_serialization_do_not_change_comparison(retrieval):
    candidate = copy.deepcopy(retrieval)
    candidate["cases"].reverse()
    unordered = dict(reversed(list(candidate.items())))
    assert compare(retrieval, signed(unordered))["differences"] == []


def test_rank_order_change_is_diagnostic(retrieval):
    candidate = copy.deepcopy(retrieval)
    ranking = row(candidate, "Q04")["diagnostics"]["ranking"]
    assert len(ranking) == 2
    ranking.reverse()
    for rank, entry in enumerate(ranking, 1):
        entry["rank"] = rank
    result = compare(retrieval, signed(candidate))
    assert result["exit_code"] == 0
    assert [entry["category"] for entry in result["differences"]] == ["warning"]
    assert result["differences"][0]["observed"][0]["document"] == ranking[0]["document"]


@pytest.mark.parametrize(("loss", "code"), [(2e-13, 0), (2e-12, 1)])
def test_retrieval_float_tolerance(retrieval, loss, code):
    candidate = copy.deepcopy(retrieval)
    change_metric(candidate, "Q01", "evidence_recall", 1 - loss)
    result = compare(retrieval, signed(candidate))
    assert result["exit_code"] == code
    if code:
        assert result["differences"][0]["field"] == "retrieval_metric_consistency.evidence_recall"


def test_improvement_informational_and_per_case_loss_visible_with_stable_mean(retrieval):
    hit = copy.deepcopy(row(retrieval, "Q02")["diagnostics"]["ranking"])
    set_single_hit(retrieval, "Q02", [])
    baseline = signed(retrieval)
    candidate = copy.deepcopy(baseline)
    set_single_hit(candidate, "Q02", hit)
    improved = compare(baseline, signed(candidate))
    assert improved["exit_code"] == 0
    assert any(item["category"] == "improvement" for item in improved["differences"])
    set_single_hit(candidate, "Q01", [])
    assert candidate["aggregates"] == baseline["aggregates"]
    result = compare(baseline, signed(candidate))
    assert result["exit_code"] == 1
    assert {
        (item["case"], item["category"])
        for item in result["differences"]
        if item["category"] != "warning"
    } == {("Q01", "regression"), ("Q02", "improvement")}


@pytest.mark.parametrize("operation", ["missing", "extra", "duplicate"])
def test_case_population(retrieval, operation):
    candidate = copy.deepcopy(retrieval)
    diagnostic = row(candidate, "Q06")
    if operation == "missing":
        candidate["cases"].remove(diagnostic)
    else:
        copy_row = copy.deepcopy(diagnostic)
        if operation == "extra":
            copy_row["id"] = "Q99"
        candidate["cases"].append(copy_row)
    for name in ("planned", "executed"):
        candidate["execution"][name] = len(candidate["cases"])
    result = compare(retrieval, signed(candidate))
    assert result["exit_code"] == (2 if operation == "duplicate" else 1)
    assert result["differences"][0]["field"] == (
        "duplicate_case" if operation == "duplicate" else "case_population"
    )


@pytest.mark.parametrize(
    ("kind", "field"),
    [
        ("retrieval", "dataset_sha256"),
        ("retrieval", "corpus_hashes"),
        ("answer", "rubric_sha256"),
        ("answer", "stimulus_sha256"),
        ("retrieval", "retrieval"),
        ("answer", "generation_parameters"),
    ],
)
def test_incompatible_identities(request, kind, field):
    baseline = request.getfixturevalue(kind)
    candidate = copy.deepcopy(baseline)
    identity = candidate["identity"]
    if field == "corpus_hashes":
        identity[field]["account-january"] = "a" * 64
    elif field == "retrieval":
        identity[field]["min_score"] = 0.06
    elif field == "generation_parameters":
        identity[field]["max_tokens"] = 451
    else:
        identity[field] = "b" * 64
    result = compare(baseline, signed(candidate))
    assert result["exit_code"] == 3
    assert result["differences"][0]["field"] == field


@pytest.mark.parametrize(("key", "value"), [("Q06", 0), ("Q01", None)])
def test_null_and_zero_are_distinct(retrieval, key, value):
    if key == "Q01":
        set_single_hit(retrieval, key, [])
    baseline = signed(retrieval)
    candidate = copy.deepcopy(baseline)
    row(candidate, key)["metrics"]["evidence_recall"] = value
    result = compare(baseline, signed(candidate))
    assert result["exit_code"] == 1
    assert result["differences"][0]["field"] == "retrieval_applicability"


@pytest.mark.parametrize(
    "changes", [{"complete": False}, {"skipped": 1}, {"errors": 1}, {"executed": 13}]
)
def test_incomplete_execution_fails(retrieval, changes):
    candidate = copy.deepcopy(retrieval)
    candidate["execution"].update(changes)
    assert compare(retrieval, signed(candidate))["exit_code"] == 1


@pytest.mark.parametrize(
    "report",
    [
        {
            "report_version": 1,
            "complete": False,
            "errors": [{"kind": "OperationalError"}],
            "skips": [],
        },
        {"report_version": 1, "complete": True, "errors": [], "skips": ["Q01"]},
        {"report_version": 1, "complete": True, "errors": ["Q01"], "skips": []},
    ],
)
def test_reduced_reports_and_report_errors_are_hard_failures(report):
    with pytest.raises(ContractError) as error:
        normalize_report("retrieval", report, {})
    assert error.value.category == "hard_failure"


def test_expected_adversarial_failure_passes_and_injected_error_is_not_infrastructure_error(answer):
    assert row(answer, "Q05", "incorrect_causality")["grade"] == "fail"
    assert row(answer, "Q06", "provider_failure")["grade"] == "execution_error"
    assert compare(answer, answer)["exit_code"] == 0
    candidate = copy.deepcopy(answer)
    changed = row(candidate, "Q05", "incorrect_causality")
    changed.update(grade="pass", expected_grade="pass")
    assert compare(answer, signed(candidate))["exit_code"] == 1


@pytest.mark.parametrize(
    ("key", "flag"), [("Q10", "retrieval_called"), ("Q11", "generation_called")]
)
def test_authorization_regression_precedes_identity_comparison(answer, key, flag):
    candidate = copy.deepcopy(answer)
    row(candidate, key, "baseline")["authorization"][flag] = True
    candidate["identity"]["dataset_sha256"] = "a" * 64
    comparison = compare(answer, signed(candidate))
    assert comparison["exit_code"] == 1
    assert comparison["differences"][0]["field"] == "authorization_rejection"


@pytest.mark.parametrize(
    ("field", "value"), [("conflict_draft", "fail"), ("public_conflict_explanation", "delivered")]
)
def test_q08_conflict_contract(answer, field, value):
    assert row(answer, "Q08", "baseline")["public_conflict_explanation"] == "unobservable"
    candidate = copy.deepcopy(answer)
    row(candidate, "Q08", "baseline")[field] = value
    assert compare(answer, signed(candidate))["exit_code"] == 1


@pytest.mark.parametrize(
    "changes", [{"model_quality_measured": True}, {"threshold_result": "pass"}]
)
def test_fake_quality_flags_fail_closed(changes):
    report = {
        "report_version": 1,
        "execution": {"complete": True, "planned": 30, "executed": 30, "errors": 0, "skipped": 0},
        "evaluator_contract_passed": True,
        "model_quality_measured": False,
        "threshold_result": None,
        **changes,
    }
    with pytest.raises(ContractError, match="offline_quality_flags"):
        normalize_report("answer", report, {})


@pytest.mark.parametrize(
    ("change", "code"), [("digest", 2), ("bool", 2), ("aggregate", 1), ("schema", 2)]
)
def test_invalid_baseline(retrieval, change, code):
    candidate = copy.deepcopy(retrieval)
    if change == "digest":
        candidate["sha256"] = "0" * 64
    elif change == "bool":
        row(candidate, "Q01")["metrics"]["evidence_recall"] = True
    elif change == "aggregate":
        candidate["aggregates"]["retrieval"]["metrics"]["evidence_recall"] = 0.7
    else:
        candidate["baseline_schema_version"] = 2
    assert (
        compare(retrieval, candidate if change == "digest" else signed(candidate))["exit_code"]
        == code
    )


@pytest.mark.parametrize(
    "payload", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '{"a":1e999}', "{"]
)
def test_invalid_source_json(payload):
    with pytest.raises(ContractError):
        parse_json(payload)


def test_missing_report_and_cli_exit(tmp_path, monkeypatch, capsys):
    absent = tmp_path / "missing.json"
    monkeypatch.setattr("sys.argv", ["compare", str(absent), str(absent)])
    assert main() == 2
    assert json.loads(capsys.readouterr().out)["result"] == "invalid"


def test_trusted_base_rejects_candidate_replacement(tmp_path, monkeypatch, retrieval, answer):
    reports = {"retrieval": retrieval, "answer": answer}
    paths = baseline_suite.PATHS
    base = "a" * 40

    def git(*args, root):
        assert root == tmp_path
        if args[0] == "rev-parse":
            return subprocess.CompletedProcess(args, 0, stdout=(base + "\n").encode())
        kind = next(kind for kind, path in paths.items() if args[1] == f"{base}:{path}")
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(reports[kind]).encode())

    monkeypatch.setattr(baseline_suite, "git", git)
    for kind, path in paths.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        baseline_suite.write_json(target, reports[kind])
    assert baseline_suite.trusted_baselines(base, tmp_path) == reports
    replacement = copy.deepcopy(retrieval)
    set_single_hit(replacement, "Q01", [])
    baseline_suite.write_json(tmp_path / paths["retrieval"], signed(replacement))
    with pytest.raises(ContractError, match="candidate_baseline_replacement"):
        baseline_suite.trusted_baselines(base, tmp_path)


def test_promotion_and_comparison_are_separate_commands(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(baseline_suite, "run", lambda _args: seen.append("run") or 0)
    monkeypatch.setattr(baseline_suite, "promote", lambda _args: seen.append("promote") or 0)
    monkeypatch.setattr(
        "sys.argv", ["suite", "run", "--base-ref", "a" * 40, "--output", str(tmp_path / "run")]
    )
    assert baseline_suite.main() == 0
    assert seen == ["run"]


@pytest.fixture
def source_retrieval(retrieval):
    from evaluation.schemas import load_document_dataset

    identity = retrieval["identity"]
    cases = []
    population = {}
    dataset = load_document_dataset().dataset
    scopes = {case.id: case.document_scope for case in dataset.cases}
    for case in retrieval["cases"]:
        row = {"id": case["id"], "track": case["track"], "status": "ok", "metrics": case["metrics"]}
        population[case["id"], ""] = {
            "scope": scopes[case["id"]],
            "track": case["track"],
            "evidence": case["evidence"],
        }
        if "authorization" in case:
            row["authorization"] = case["authorization"]
        else:
            row["results"] = case["diagnostics"]["ranking"]
            row["retrieved_count"] = len(row["results"])
            row["latency"] = {"retrieval_ms": 4.1}
        cases.append(row)
    raw = {
        **{
            key: identity[key]
            for key in (
                "report_version",
                "mode",
                "dataset_schema_version",
                "dataset_version",
                "corpus_version",
                "corpus_hashes",
                "embedding",
                "retrieval",
                "chunking",
            )
        },
        "database": {**identity["database"], "pgvector_used": True},
        "pdf_renderer": identity["renderer"],
        "cases": cases,
        "aggregates": retrieval["aggregates"],
        "errors": [],
        "skips": [],
        "complete": True,
        **{key: retrieval["source"][key] for key in ("git_commit", "working_tree_dirty")},
    }
    context = {
        **retrieval["source"],
        "dataset_sha256": identity["dataset_sha256"],
        "corpus_hashes": identity["corpus_hashes"],
        "pgvector_image": identity["pgvector_image"],
        "populations": {"retrieval": population},
    }
    return raw, context


def test_source_latency_and_unrecognized_payload_do_not_enter_normalized_artifact(
    retrieval, source_retrieval
):
    raw, context = source_retrieval
    cases = raw["cases"]
    first = normalize_report("retrieval", raw, context)
    cases[0]["latency"]["retrieval_ms"] = 900
    cases[0]["raw_prompt"] = "MUST_NOT_APPEAR"
    raw["database"]["url"] = "MUST_NOT_APPEAR"
    raw["cases"].reverse()
    second = normalize_report("retrieval", raw, context)
    assert first == second == retrieval
    assert "MUST_NOT_APPEAR" not in json.dumps(second)


def test_normalized_candidate_cannot_rank_foreign_document(retrieval):
    candidate = copy.deepcopy(retrieval)
    row(candidate, "Q01")["diagnostics"]["ranking"][0]["document"] = "private-plan"
    result = compare(retrieval, signed(candidate))
    assert result["exit_code"] == 1
    assert result["differences"][0]["field"] == "ranked_document"


def test_empty_source_q01_cannot_keep_positive_metrics(source_retrieval):
    raw, context = source_retrieval
    row(raw, "Q01").update(results=[], retrieved_count=0)
    with pytest.raises(ContractError, match="retrieval_metric_consistency"):
        normalize_report("retrieval", raw, context)


def test_resealed_empty_normalized_q01_cannot_keep_positive_metrics(retrieval):
    candidate = copy.deepcopy(retrieval)
    diagnostic = row(candidate, "Q01")["diagnostics"]
    diagnostic["ranking"] = []
    diagnostic["retrieved_count"] = 0
    result = compare(retrieval, signed(candidate))
    assert result["exit_code"] == 1
    assert result["differences"][0]["field"] == "retrieval_metric_consistency.evidence_recall"


@pytest.mark.parametrize("normalized", [False, True])
def test_nonempty_ranking_with_wrong_count_fails(retrieval, source_retrieval, normalized):
    if normalized:
        row(retrieval, "Q01")["diagnostics"]["retrieved_count"] = 0
        result = compare(signed(retrieval), signed(retrieval))
        assert result["exit_code"] == 2
        assert result["differences"][0]["field"] == "retrieved_count"
    else:
        raw, context = source_retrieval
        row(raw, "Q01")["retrieved_count"] = 0
        with pytest.raises(ContractError, match="retrieved_count"):
            normalize_report("retrieval", raw, context)


def test_distractor_only_ranking_cannot_claim_evidence(retrieval):
    candidate = copy.deepcopy(retrieval)
    diagnostic = row(candidate, "Q09")["diagnostics"]
    distractor = next(
        item for item in diagnostic["ranking"] if item["document"] == "distractor-usd"
    )
    diagnostic.update(ranking=[{**distractor, "rank": 1}], retrieved_count=1)
    result = compare(retrieval, signed(candidate))
    assert result["exit_code"] == 1
    assert result["differences"][0]["field"] == "retrieval_metric_consistency.evidence_recall"


@pytest.mark.parametrize("field", ["evidence_recall", "evidence_coverage"])
def test_partial_evidence_cannot_claim_full_coverage(retrieval, field):
    candidate = copy.deepcopy(retrieval)
    case = row(candidate, "Q01")
    start, end = case["evidence"][0]["span"]
    assert end - start > 1
    case["diagnostics"]["ranking"][0]["span"] = [start, start + 1]
    # For a one-token overlap, recall and novel precision are zero.
    # Coverage is 1 / passage length, conventional precision 1/5, MRR 1.
    for name, expected in (
        ("evidence_recall", 0),
        ("evidence_coverage", 1 / (end - start)),
        ("novel_evidence_precision", 0),
    ):
        if name != field:
            change_metric(candidate, "Q01", name, expected)
    result = compare(retrieval, signed(candidate))
    assert result["exit_code"] == 1
    assert result["differences"][0]["field"] == f"retrieval_metric_consistency.{field}"


@pytest.mark.parametrize(
    ("metric", "incorrect"),
    [
        ("mrr", 0.5),
        ("chunk_precision", 0.4),
        ("novel_evidence_precision", 0.4),
    ],
)
def test_wrong_metric_cannot_hide_behind_matching_aggregate(retrieval, metric, incorrect):
    candidate = copy.deepcopy(retrieval)
    # Q01 has one relevant hit at rank 1 and k=5. Change both the
    # per-case value and macro-average so aggregate validation alone passes.
    change_metric(candidate, "Q01", metric, incorrect)
    result = compare(retrieval, signed(candidate))
    assert result["exit_code"] == 1
    assert result["differences"][0]["field"] == f"retrieval_metric_consistency.{metric}"


def test_mrr_follows_first_relevant_hit_after_a_distractor(retrieval):
    candidate = copy.deepcopy(retrieval)
    ranking = row(candidate, "Q09")["diagnostics"]["ranking"]
    assert [item["document"] for item in ranking] == ["account-january", "distractor-usd"]
    ranking.reverse()
    for rank, item in enumerate(ranking, 1):
        item["rank"] = rank
    result = compare(retrieval, signed(candidate))
    assert result["exit_code"] == 1
    assert result["differences"][0]["field"] == "retrieval_metric_consistency.mrr"
    change_metric(candidate, "Q09", "mrr", 0.5)
    result = compare(retrieval, signed(candidate))
    assert result["exit_code"] == 1
    assert any(
        item["category"] == "regression" and item["field"] == "metrics.mrr"
        for item in result["differences"]
    )
