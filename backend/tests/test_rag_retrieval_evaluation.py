import asyncio
import os

import pytest

from evaluation.retrieval_metrics import METRICS
from evaluation.retrieval_runner import aggregates, evaluate_retrieval, validate_test_database_url
from evaluation.schemas import load_document_dataset


@pytest.mark.parametrize(
    "url",
    [
        None,
        "sqlite://",
        "not a database URL",
        "postgresql+psycopg://example.invalid/eval",
        "postgresql+psycopg://localhost/eval?hostaddr=192.0.2.1",
    ],
)
def test_requires_explicit_local_postgres_url(url):
    with pytest.raises(ValueError):
        validate_test_database_url(url)


def test_failed_applicable_case_invalidates_aggregate():
    results = [
        {"track": "retrieval", "status": "ok", "metrics": dict.fromkeys(METRICS, 1.0)},
        {"track": "retrieval", "status": "error", "metrics": dict.fromkeys(METRICS)},
    ]
    assert aggregates(results)["retrieval"] == {
        "applicable_cases": 2,
        "measured_cases": 1,
        "failed_cases": 1,
        "metrics": dict.fromkeys(METRICS),
    }


def test_document_retrieval_runs_real_uploads_and_pgvector():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL with isolated PostgreSQL/pgvector is required")
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        report = runner.run(evaluate_retrieval(url))
        repeat = runner.run(evaluate_retrieval(url))
    assert report["complete"], report["errors"]
    assert report["database"]["pgvector_used"]
    assert report["database"]["pgvector_version"]
    assert report["embedding"]["dimensions"] == 1536
    assert report["embedding"]["model"] == "deterministic-local-hash-v2"
    assert report["aggregates"]["retrieval"]["applicable_cases"] == 8
    assert report["aggregates"]["conflict"]["applicable_cases"] == 1

    cases = {case["id"]: case for case in report["cases"]}
    dataset = load_document_dataset().dataset
    assert set(cases) == {case.id for case in dataset.cases}
    for case in dataset.cases:
        row = cases[case.id]
        if case.id in {"Q10", "Q11"}:
            assert row["authorization"] == {
                "http_status": 404,
                "retrieval_called": False,
                "generation_called": False,
                "passed": True,
            }
            assert row["metrics"] == dict.fromkeys(METRICS)
            continue
        assert {chunk["document"] for chunk in row["results"]} <= set(case.document_scope)
        assert "private-plan" not in {chunk["document"] for chunk in row["results"]}
        scores = [chunk["score"] for chunk in row["results"]]
        assert scores == sorted(scores, reverse=True)
        assert row["latency"]["vector_sql_execute_ms"] >= 0
        if case.id in {"Q06", "Q07", "Q12"}:
            assert row["metrics"] == dict.fromkeys(METRICS)
    assert [chunk["document"] for chunk in cases["Q09"]["results"]] == [
        "account-january",
        "distractor-usd",
    ]
    assert cases["Q09"]["metrics"]["chunk_precision"] == 0.2
    assert report["aggregates"] == repeat["aggregates"]
    assert [
        {key: value for key, value in case.items() if key != "latency"} for case in report["cases"]
    ] == [
        {key: value for key, value in case.items() if key != "latency"} for case in repeat["cases"]
    ]
