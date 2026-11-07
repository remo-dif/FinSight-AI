import asyncio
import json
import os
import socket
from decimal import Decimal

import httpx
import pytest

from evaluation.real_model_contract import ORIGIN, Budget, Profile, digest, plan_for
from evaluation.real_model_provider import (
    EMBEDDINGS,
    AsyncTransport,
    Boundary,
    Journal,
    Phase,
    SafetyError,
    SyncTransport,
)
from evaluation.real_model_runner import main, run_async


@pytest.fixture
def profile():
    return Profile(
        schema_version=1,
        origin=ORIGIN,
        model="gpt-4o",
        embedding_backend="openai",
        embedding_model="text-embedding-3-small",
        input_per_million="1",
        output_per_million="2",
        embedding_per_million="1",
        pricing_source="https://openai.com/api/pricing/",
        pricing_date="2026-11-07",
        repetitions=1,
    )


@pytest.fixture
def budget():
    return Budget(requests=30, tokens=1_000_000, estimated_cost="10")


def test_plan_is_offline(profile, tmp_path, monkeypatch, capsys):
    path = tmp_path / "profile.json"
    path.write_text(profile.model_dump_json())

    def forbidden(*args, **kwargs):
        pytest.fail("Offline plan initialized network or a provider")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(httpx.Client, "__init__", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", forbidden)
    assert main(["plan", "--profile", str(path)]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert len(plan["units"]) == 14
    assert plan["request_upper_bound"] == 30
    assert len(plan["corpus"]) == 6


def test_paid_opt_in_and_credentials(profile, tmp_path, monkeypatch):
    path = tmp_path / "profile.json"
    path.write_text(profile.model_dump_json())
    output = tmp_path / "out"
    args = [
        "run",
        "--profile",
        str(path),
        "--max-requests",
        "30",
        "--max-tokens",
        "1000000",
        "--max-estimated-cost",
        "10",
        "--output",
        str(output),
    ]
    assert main(args) == 2
    monkeypatch.delenv("FINSIGHT_EVAL_OPENAI_API_KEY", raising=False)
    assert main([*args, "--allow-paid"]) == 2
    assert not output.exists()
    with pytest.raises(ValueError):
        Profile.model_validate(profile.model_dump() | {"origin": "https://example.org"})


def embedding_request(profile, destination=ORIGIN, values=None):
    return httpx.Request(
        "POST",
        destination + EMBEDDINGS,
        json={
            "input": values or ["approved"],
            "dimensions": 1536,
            "model": profile.embedding_model,
        },
    )


@pytest.mark.parametrize(("requests", "tokens", "cost"), [(2, 1, "2"), (2, 10000, "0.00000001")])
def test_budget_denied_before_network(profile, tmp_path, requests, tokens, cost):
    journal = Journal(
        tmp_path / "journal", {}, Budget(requests=requests, tokens=tokens, estimated_cost=cost)
    )
    try:
        boundary = Boundary(profile, journal, "secret-placeholder")
        with boundary.during(Phase("test", embedding_input=["approved"])):
            with pytest.raises(SafetyError, match="budget"):
                SyncTransport(boundary, lambda _: pytest.fail("egress")).handle_request(
                    embedding_request(profile)
                )
        assert journal.db.execute("SELECT count(*) FROM attempts").fetchone() == (0,)
    finally:
        journal.db.close()


def test_request_count_and_safe_resume(profile, tmp_path):
    budget = Budget(requests=1, tokens=10000, estimated_cost="1")
    path = tmp_path / "journal"
    journal = Journal(path, {"plan": "original"}, budget)
    boundary = Boundary(profile, journal, "secret-placeholder")
    calls = []

    def send(request):
        calls.append(request)
        assert journal.db.execute("SELECT response FROM attempts").fetchone() == (None,)
        return httpx.Response(200, json={"model": profile.embedding_model})

    transport = SyncTransport(boundary, send)
    with boundary.during(Phase("first", embedding_input=["approved"])):
        transport.handle_request(embedding_request(profile))
        with pytest.raises(SafetyError):
            transport.handle_request(embedding_request(profile))
    journal.db.close()
    journal = Journal(path, {"plan": "original"}, budget)
    boundary.journal = journal
    try:
        journal.assert_resumable()
        with boundary.during(Phase("first", embedding_input=["approved"])):
            transport.handle_request(embedding_request(profile))
        with boundary.during(Phase("second", embedding_input=["approved"])):
            with pytest.raises(SafetyError, match="budget"):
                transport.handle_request(embedding_request(profile))
        assert len(calls) == 1
        tokens, cost, usage = journal.db.execute(
            "SELECT input_tokens + output_tokens, cost, usage FROM attempts"
        ).fetchone()
        assert tokens > 0 and Decimal(cost) > 0 and usage is None
        with pytest.raises(SafetyError):
            Journal(path, {"plan": "tampered"}, budget)
    finally:
        journal.db.close()


@pytest.mark.parametrize("outcome", ["timeout", "redirect", "secret"])
def test_uncertain_delivery_is_never_replayed(profile, budget, tmp_path, outcome):
    path = tmp_path / "journal"
    journal = Journal(path, {}, budget)
    boundary = Boundary(profile, journal, "never-persist-this-key")

    def send(request):
        if outcome == "timeout":
            raise httpx.ReadTimeout("timeout", request=request)
        if outcome == "redirect":
            return httpx.Response(307, headers={"location": "https://example.org"})
        return httpx.Response(200, json={"content": "never-persist-this-key"})

    with boundary.during(Phase("test", embedding_input=["approved"])):
        with pytest.raises((httpx.ReadTimeout, SafetyError)):
            SyncTransport(boundary, send).handle_request(embedding_request(profile))
    journal.db.close()
    assert b"never-persist-this-key" not in path.read_bytes()
    journal = Journal(path, {}, budget)
    try:
        with pytest.raises(SafetyError, match="Uncertain"):
            journal.assert_resumable()
    finally:
        journal.db.close()


@pytest.mark.parametrize("destination", ["http://api.openai.com", "https://example.org", ORIGIN])
def test_async_boundary_denies_wrong_destination_or_content(profile, budget, tmp_path, destination):
    journal = Journal(tmp_path / "journal", {}, budget)
    boundary = Boundary(profile, journal, "secret-placeholder")
    try:
        with boundary.during(Phase("test", embedding_input=["approved"])):
            with pytest.raises(SafetyError):
                asyncio.run(
                    AsyncTransport(boundary, lambda _: pytest.fail("egress")).handle_async_request(
                        embedding_request(profile, destination, ["unapproved"])
                    )
                )
    finally:
        journal.db.close()


def test_real_asgi_with_simulated_provider(profile, budget, tmp_path, monkeypatch):
    url = os.environ.get("FINSIGHT_TEST_PR5_DATABASE_URL")
    if not url:
        pytest.skip("Dedicated PR5 PostgreSQL/pgvector URL is unavailable")
    from app.services.rag import RagService
    from evaluation.real_model_execution import execute

    def forbidden(*args, **kwargs):
        pytest.fail("Integration test attempted real provider egress")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    identity = {"plan": plan_for(profile)}
    path = tmp_path / "journal"
    journal = Journal(path, {"manifest": digest(identity)}, budget)
    calls = []

    def provider(request):
        payload = json.loads(request.content)
        calls.append(request.url.path)
        if request.url.path == EMBEDDINGS:
            return httpx.Response(
                200,
                json={
                    "model": profile.embedding_model,
                    "data": [
                        {
                            "object": "embedding",
                            "index": index,
                            "embedding": RagService._local_embedding(value),
                        }
                        for index, value in enumerate(payload["input"])
                    ],
                    "usage": {"total_tokens": 5, "prompt_tokens": 5},
                },
            )
        return httpx.Response(
            200,
            json={
                "model": profile.model,
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"answer": "", "references": [], "abstained": True}
                            )
                        }
                    }
                ],
                "usage": {"total_tokens": 5, "prompt_tokens": 4, "completion_tokens": 1},
            },
        )

    async def async_provider(request):
        return provider(request)

    try:
        for index in range(2):
            summary = run_async(
                execute(
                    profile,
                    journal,
                    "offline-simulated-only",
                    url,
                    tmp_path,
                    identity,
                    sync_send=provider,
                    async_send=async_provider,
                )
            )
            assert summary["completed"] == 14, (summary, index)
            assert summary["errors"] == 0
            assert summary["per_case"]["Q10"]["authorization"] == {"pass": 1}
            assert summary["per_case"]["Q11"]["authorization"] == {"pass": 1}
            assert calls.count(EMBEDDINGS) == 18
            assert "/v1/chat/completions" in calls
            assert len(calls) == len(summary["requests"])
            assert summary["aggregates"]["evidence_recall"]["denominator"] > 0
            assert summary["usage_unknown"] == 0
    finally:
        journal.db.close()


def test_journal_detects_observation_tampering(tmp_path, budget):
    journal = Journal(tmp_path / "journal", {}, budget)
    try:
        journal.observe("Q01:01", {"error": None})
        journal.assert_resumable()
        with journal.transaction():
            journal.db.execute("UPDATE observations SET body='{}'")
        with pytest.raises(SafetyError, match="integrity"):
            journal.assert_resumable()
    finally:
        journal.db.close()


@pytest.mark.parametrize(
    ("case_id", "answer_style", "dimension", "expected"),
    [
        ("Q05", "amounts_only", "required_causal_relationship", "fail"),
        ("Q05", "incorrect_cause", "required_causal_relationship", "fail"),
        ("Q05", "free_form", "required_causal_relationship", "needs_review"),
        ("Q05", "valid_distractor", "citation_support", "fail"),
        ("Q05", "all_facts", "required_causal_relationship", "pass"),
        ("Q08", "all_facts", "conflict", "pass"),
        ("Q08", "free_form", "conflict", "needs_review"),
        ("Q08", "answers_conflict", "abstention", "fail"),
        ("Q08", "provider_error", "operational_reliability", "fail"),
    ],
)
def test_grade_separates_semantics_and_geometry(case_id, answer_style, dimension, expected):
    from evaluation.answer_rubric import load_answer_rubric
    from evaluation.real_model_grading import grade
    from evaluation.schemas import load_document_dataset

    bundle = load_document_dataset()
    rubric = next(case for case in load_answer_rubric(bundle).cases if case.id == case_id)
    doc = "budget-february" if case_id == "Q08" else "revenue-january"
    passages = {
        (ref.document_key, ref.evidence_key): (1, 2)
        for fact in rubric.facts
        for group in fact.support
        for ref in group
    }
    facts = [
        fact
        for fact in rubric.facts
        if answer_style != "amounts_only" or fact.kind != "relationship"
    ]
    answer = "\n".join(
        f"{fact.id}: {'not ' if answer_style == 'incorrect_cause' and fact.kind == 'relationship' else ''}{fact.value}"
        for fact in facts
    )
    if answer_style == "free_form":
        answer = "An explanation requiring a semantic reviewer."
    abstained = case_id == "Q08" and answer_style != "answers_conflict"
    verified = {"reference": ("other" if answer_style == "valid_distractor" else doc, [0, 3])}
    public = {
        "status": "abstained" if abstained else "ok",
        "abstained": abstained,
        "answer": "I could not find enough supporting evidence in the selected documents to answer."
        if abstained
        else answer,
        "citations": [] if abstained else [{"reference": "reference"}],
    }
    result = grade(
        {
            "ranking": [{"document": doc, "span": [0, 3]}],
            "public": public,
            "error": "timeout" if answer_style == "provider_error" else None,
            "parsed_draft": {"answer": answer, "abstained": abstained, "references": []},
            "verified_citations": verified,
            "prompt_references": ["reference"],
        },
        rubric,
        passages,
        5,
    )
    assert result["retrieval_metrics"]["evidence_recall"] == 1
    assert result[dimension] == expected


def test_resume_refuses_empty_replacement_journal(tmp_path, budget):
    path = tmp_path / "journal"
    path.touch()
    with pytest.raises(SafetyError, match="original initialized journal"):
        Journal(path, {"manifest": "original"}, budget, resume=True)
