import asyncio
import json
import os
import socket
import sqlite3
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
from evaluation.real_model_runner import exit_status, main, run_async


@pytest.fixture(autouse=True)
def prohibit_real_provider_egress(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("PR5 test attempted real HTTP egress")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)


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
        with (
            boundary.during(Phase("test", embedding_input=["approved"])),
            pytest.raises(SafetyError, match="budget"),
        ):
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
        with (
            boundary.during(Phase("second", embedding_input=["approved"])),
            pytest.raises(SafetyError, match="budget"),
        ):
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

    with (
        boundary.during(Phase("test", embedding_input=["approved"])),
        pytest.raises((httpx.ReadTimeout, SafetyError)),
    ):
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
        with (
            boundary.during(Phase("test", embedding_input=["approved"])),
            pytest.raises(SafetyError),
        ):
            asyncio.run(
                AsyncTransport(boundary, lambda _: pytest.fail("egress")).handle_async_request(
                    embedding_request(profile, destination, ["unapproved"])
                )
            )
    finally:
        journal.db.close()


@pytest.mark.parametrize("terminal_failure", [False, True])
def test_real_asgi_with_simulated_provider(
    profile, budget, tmp_path, monkeypatch, terminal_failure
):
    url = os.environ.get("FINSIGHT_TEST_PR5_DATABASE_URL")
    if not url:
        pytest.skip("Dedicated PR5 PostgreSQL/pgvector URL is unavailable")
    from app.services.rag import RagService
    from evaluation.real_model_execution import execute

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
                            "content": "invalid JSON"
                            if terminal_failure
                            and "ALPHA closing balance on 31 January"
                            in payload["messages"][1]["content"]
                            else json.dumps({"answer": "", "references": [], "abstained": True})
                        }
                    }
                ],
                "usage": {"total_tokens": 5, "prompt_tokens": 4, "completion_tokens": 1},
            },
        )

    async def async_provider(request):
        return provider(request)

    def execute_once():
        return run_async(
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

    try:
        summary = execute_once()
        original = journal.db.execute("SELECT * FROM observations ORDER BY unit").fetchall()
        send_count = len(calls)
        assert summary["terminal_observations"] == 14
        assert summary["operational_failures"] == int(terminal_failure)
        assert exit_status(summary) == int(terminal_failure)
        assert summary["per_case"]["Q10"]["authorization"] == {"pass": 1}
        assert summary["per_case"]["Q11"]["authorization"] == {"pass": 1}
        assert calls.count(EMBEDDINGS) == 18
        assert "/v1/chat/completions" in calls
        assert send_count == len(summary["requests"])
        assert summary["aggregates"]["evidence_recall"]["denominator"] > 0
        assert summary["usage_unknown"] == 0
        if terminal_failure:
            row = json.loads(original[0][1])
            assert row["observation"]["error"] == "model_response_parse_failure"
            assert row["grade"]["operational_reliability"] == "fail"
            assert row["grade"]["abstention"] == "not_applicable"

        resumed = execute_once()
        assert resumed == summary
        assert len(calls) == send_count
        assert journal.db.execute("SELECT * FROM observations ORDER BY unit").fetchall() == original

        # Simulate interruption after provider confirmation and before recording the case.
        with journal.transaction():
            journal.db.execute("DELETE FROM observations WHERE unit='Q01:01'")
        resumed = execute_once()
        assert resumed["terminal_observations"] == 14
        assert resumed["reused_confirmed_responses"] == 8  # six PDF embeddings, query and draft
        assert len(calls) == send_count
        assert journal.db.execute("SELECT * FROM observations ORDER BY unit").fetchall() == original

        with journal.transaction():
            journal.db.execute("DELETE FROM observations WHERE unit='Q01:01'")
        journal.observe("Q01:01", {"observation": {"error": "evaluation_contract_error"}})
        with pytest.raises(SafetyError, match="Incomplete observation"):
            execute_once()
        assert len(calls) == send_count

    finally:
        journal.db.close()


def test_journal_detects_observation_tampering(tmp_path, budget):
    journal = Journal(tmp_path / "journal", {}, budget)
    try:
        journal.observe("Q01:01", {"observation": {"error": None}})
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


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    ("outcome", "state", "error"),
    [
        ("below", "confirmed", None),
        ("equal", "confirmed", None),
        ("above", "rejected", "usage_exceeded_reservation"),
        ("missing", "confirmed", None),
        ("invalid", "rejected", "invalid_provider_usage"),
        ("invalid_split", "rejected", "invalid_provider_usage"),
        ("above_split", "rejected", "usage_exceeded_reservation"),
        ("http", "rejected", "provider_http_error"),
        ("network", "uncertain", None),
        ("interruption", "uncertain", None),
    ],
)
def test_usage_attempt_state_and_reuse(
    profile, budget, tmp_path, asynchronous, outcome, state, error
):
    path = tmp_path / "journal"
    journal = Journal(path, {}, budget)
    boundary = Boundary(profile, journal, "secret-placeholder")
    calls = []

    def send(request):
        calls.append(request)
        phase_state, reserved = journal.db.execute(
            "SELECT state, input_tokens + output_tokens FROM attempts"
        ).fetchone()
        assert phase_state == "uncertain"
        if outcome == "network":
            raise httpx.ReadTimeout("simulated", request=request)
        if outcome == "interruption":
            raise KeyboardInterrupt
        if outcome == "http":
            return httpx.Response(503, text="discard untrusted error body")
        body = {"model": profile.embedding_model}
        if outcome != "missing":
            tokens = {
                "below": reserved - 1,
                "equal": reserved,
                "above": reserved + 1,
                "invalid": True,
                "invalid_split": 2,
                "above_split": 1,
            }[outcome]
            body["usage"] = {"total_tokens": tokens}
            if outcome == "invalid_split":
                body["usage"].update(prompt_tokens=1, completion_tokens=0)
            if outcome == "above_split":
                body["usage"].update(prompt_tokens=0, completion_tokens=1)
        return httpx.Response(200, json=body)

    async def send_async(request):
        return send(request)

    def invoke(values=None):
        request = embedding_request(profile, values=values)
        if asynchronous:
            return asyncio.run(AsyncTransport(boundary, send_async).handle_async_request(request))
        return SyncTransport(boundary, send).handle_request(request)

    try:
        with boundary.during(Phase("unit", embedding_input=["approved"])):
            if state == "confirmed":
                invoke()
            else:
                with pytest.raises((SafetyError, httpx.ReadTimeout, KeyboardInterrupt)):
                    invoke()
        row = journal.db.execute(
            "SELECT state, error, response, usage, input_tokens + output_tokens, cost FROM attempts"
        ).fetchone()
        assert row[:2] == (state, error)
        assert (row[2] is None) == (state == "uncertain")
        if outcome == "above":
            assert int(row[3]) == row[4] + 1
            assert json.loads(row[2])["body"]["usage"]["total_tokens"] == int(row[3])
        assert row[4] > 0 and Decimal(row[5]) > 0
    finally:
        journal.db.close()

    journal = Journal(path, {}, budget, resume=True)
    boundary.journal = journal
    try:
        if state == "confirmed":
            journal.assert_resumable()
            with boundary.during(Phase("unit", embedding_input=["approved"])):
                invoke()
            assert boundary.reused == 1
            with (
                boundary.during(Phase("unit", embedding_input=["changed"])),
                pytest.raises(SafetyError),
            ):
                invoke(["changed"])
        else:
            with pytest.raises(SafetyError):
                journal.assert_resumable()
            with (
                boundary.during(Phase("unit", embedding_input=["approved"])),
                pytest.raises(SafetyError),
            ):
                invoke()
        assert len(calls) == 1
        assert journal.db.execute(
            "SELECT state, error, response, usage, input_tokens + output_tokens, cost FROM attempts"
        ).fetchall() == [row]
    finally:
        journal.db.close()


def test_crash_before_transport_preserves_reservation(budget, tmp_path):
    path = tmp_path / "journal"
    journal = Journal(path, {}, budget)
    journal.reserve("unit", EMBEDDINGS, "digest", 300, 0, Decimal("0.1"))
    journal.db.close()
    journal = Journal(path, {}, budget, resume=True)
    try:
        assert journal.db.execute("SELECT state, input_tokens, cost FROM attempts").fetchall() == [
            ("reserved", 300, "0.1")
        ]
        with pytest.raises(SafetyError):
            journal.assert_resumable()
        with pytest.raises(SafetyError):
            journal.reserve("unit", EMBEDDINGS, "digest", 300, 0, Decimal("0.1"))
    finally:
        journal.db.close()


def test_exit_status_distinguishes_terminal_failure_and_incomplete():
    summary = {
        "planned": 2,
        "successful_evaluations": 1,
        "operational_failures": 1,
        "incomplete_units": 0,
        "run_error": None,
        "uncertain_attempts": 0,
        "reserved_attempts": 0,
        "rejected_attempts": 0,
    }
    assert exit_status(summary) == 1
    assert exit_status(summary | {"incomplete_units": 1}) == 2
    assert exit_status(summary | {"rejected_attempts": 1}) == 2
    assert exit_status(summary | {"successful_evaluations": 2, "operational_failures": 0}) == 0


def test_corrupt_and_missing_journal_blocks_resume(tmp_path, budget):
    path = tmp_path / "journal"
    with pytest.raises(SafetyError):
        Journal(path, {}, budget, resume=True)
    path.write_bytes(b"not SQLite")
    with pytest.raises(sqlite3.DatabaseError):
        Journal(path, {}, budget, resume=True)


def test_v1_journal_is_not_migrated(tmp_path, budget):
    path = tmp_path / "journal"
    journal = Journal(path, {}, budget)
    with journal.transaction():
        identity = json.loads(journal.db.execute("SELECT identity FROM manifest").fetchone()[0])
        identity["version"] = 1
        journal.db.execute("UPDATE manifest SET identity=?", (json.dumps(identity),))
    journal.db.close()
    with pytest.raises(SafetyError, match="version"):
        Journal(path, {}, budget, resume=True)
    with sqlite3.connect(path) as db:
        assert json.loads(db.execute("SELECT identity FROM manifest").fetchone()[0])["version"] == 1


def test_offline_terminal_and_incomplete_observation_policy(tmp_path, budget):
    journal = Journal(tmp_path / "journal", {}, budget)
    try:
        record = {
            "case": "Q01",
            "repetition": 1,
            "observation": {"error": "model_response_parse_failure"},
            "grade": {"operational_reliability": "fail"},
        }
        journal.observe("Q01:01", record)
        journal.assert_resumable({"Q01:01"})
        body, state = journal.db.execute("SELECT body, state FROM observations").fetchone()
        assert (json.loads(body), state) == (record, "operational_failure")
        journal.observe(
            "Q01:02", record | {"repetition": 2, "observation": {"error": "authorization_failure"}}
        )
        with pytest.raises(SafetyError, match="Incomplete observation"):
            journal.assert_resumable({"Q01:01", "Q01:02"})
        assert journal.db.execute("SELECT count(*) FROM attempts").fetchone() == (0,)
    finally:
        journal.db.close()
