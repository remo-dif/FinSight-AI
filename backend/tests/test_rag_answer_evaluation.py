import asyncio
import json
import os

import pytest
from sqlalchemy import create_engine, text

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_KEY", "evaluation-test-access-placeholder-1234567890")
os.environ.setdefault("JWT_REFRESH_SECRET_KEY", "evaluation-test-refresh-placeholder-1234567890")
os.environ.setdefault("OPENAI_API_KEY", "evaluation-placeholder-not-provider")

from evaluation.answer_rubric import RUBRIC_PATH, load_answer_rubric
from evaluation.answer_runner import evaluate_answers, verified_citations
from evaluation.retrieval_runner import validate_test_database_url
from evaluation.schemas import load_document_dataset


@pytest.mark.parametrize(
    "mutation",
    [
        "hash",
        "duplicate",
        "missing",
        "outcome",
        "unknown_anchor",
        "foreign_anchor",
        "empty_group",
        "bad_value",
        "bad_equation",
    ],
)
def test_invalid_rubric_fails_before_execution(mutation, tmp_path):
    raw = json.loads(RUBRIC_PATH.read_bytes())
    first = raw["cases"][0]
    if mutation == "hash":
        raw["dataset_sha256"] = "0" * 64
    elif mutation == "duplicate":
        raw["cases"].append(first)
    elif mutation == "missing":
        raw["cases"].pop()
    elif mutation == "outcome":
        first["outcome"] = "abstention_required"
    elif mutation == "unknown_anchor":
        first["facts"][0]["support"][0][0]["evidence_key"] = "unknown"
    elif mutation == "foreign_anchor":
        first["facts"][0]["support"][0][0] = {
            "document_key": "private-plan",
            "evidence_key": "private",
        }
    elif mutation == "empty_group":
        first["facts"][0]["support"] = [[]]
    elif mutation == "bad_value":
        first["facts"][0]["value"] = "NaN EUR @ 2025-01"
    else:
        raw["cases"][3]["facts"][0]["value"] = "250 = 325 EUR @ 2025-01"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError):
        load_answer_rubric(load_document_dataset(), path)


@pytest.fixture
def pg_url():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL with isolated PostgreSQL/pgvector is required")
    return validate_test_database_url(url)


def schema_names(url):
    engine = create_engine(url)
    try:
        with engine.connect() as db:
            return set(
                db.scalars(text("SELECT nspname FROM pg_namespace WHERE nspname LIKE 'rag_eval_%'"))
            )
    finally:
        engine.dispose()


def test_real_answer_evaluation_and_repeatability(pg_url):
    before = schema_names(pg_url)
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        report = runner.run(evaluate_answers(pg_url))
        repeat = runner.run(evaluate_answers(pg_url))
    assert schema_names(pg_url) == before
    assert report == repeat
    assert report["execution"] == {
        "complete": True,
        "planned": 28,
        "executed": 28,
        "errors": 0,
        "skipped": 0,
    }
    assert report["evaluator_contract_passed"], [
        row for row in report["cases"] if not row["contract_passed"]
    ]
    assert report["authorization"] == {"planned": 2, "passed": 2, "contract_passed": True}
    assert report["model_quality_measured"] is False
    assert report["threshold_result"] is None
    assert report["baseline_aggregate"]["pass"] == 14
    assert report["baseline_aggregate"]["metrics"]["abstention_correctness"]["applicable"] == 3
    rows = {(row["id"], row["scenario"]): row for row in report["cases"]}
    assert rows["Q04", "baseline"]["grade"]["metrics"]["citation_completeness"] == 1
    assert rows["Q04", "incomplete_citations"]["grade"]["metrics"]["citation_completeness"] == 0
    assert rows["Q08", "baseline"]["conflict_draft"] == "pass"
    assert rows["Q08", "baseline"]["public_conflict_explanation"] == "unobservable"
    assert rows["Q08", "discarded_reconciliation"]["conflict_draft"] == "fail"
    assert rows["Q06", "discarded_fabrication"]["draft_warning"] == "discarded_unexpected_claim"
    assert rows["Q06", "discarded_fabrication"]["public_citation_count"] == 0
    for scenario in ("malformed_json", "provider_failure"):
        assert rows["Q06", scenario]["parsed_status"] == "provider_error"
        assert rows["Q06", scenario]["grade"]["status"] == "execution_error"
    assert rows["Q09", "foreign_reference"]["api_status"] == "abstained"
    assert rows["Q09", "duplicate_reference"]["public_citation_count"] == 1
    serialized = json.dumps(report)
    for forbidden in (
        "closing-balance: 1,350.00",
        "SYNTHETIC EVALUATION DOCUMENT",
        "Bearer ",
        "postgresql+psycopg://",
    ):
        assert forbidden not in serialized


def test_failed_ingestion_cleans_up_owned_schema_and_storage(pg_url, monkeypatch):
    before = schema_names(pg_url)
    paths = []

    from evaluation import retrieval_runner

    original = retrieval_runner.ingest_corpus

    async def fail_after_upload(*args):
        paths.append(args[-1])
        await original(*args)
        raise RuntimeError("synthetic setup failure")

    monkeypatch.setattr(retrieval_runner, "ingest_corpus", fail_after_upload)
    with (
        asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner,
        pytest.raises(RuntimeError, match="synthetic setup failure"),
    ):
        runner.run(evaluate_answers(pg_url))
    assert schema_names(pg_url) == before
    assert paths and not paths[0].exists()


def test_public_sources_cannot_leak_when_generation_never_runs():
    persisted = {"private": ("private-plan", "id", "other", 0, "hash", "secret", (0, 1))}
    public = {"sources": [{"reference": "private"}], "citations": []}
    with pytest.raises(ValueError, match="ownership"):
        verified_citations(public, {}, persisted, ["account-january"], "owner")
