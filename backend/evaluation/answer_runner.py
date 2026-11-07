"""Offline document-Q&A evaluation through the authenticated application."""

import argparse
import asyncio
import json
import logging
import os
import subprocess
from dataclasses import asdict, dataclass
from types import SimpleNamespace
from unittest.mock import patch

from openai import OpenAIError

from app.core.config import settings
from app.core.openai_resilience import CircuitBreaker
from app.models.embedding import EMBEDDING_DIMENSIONS
from app.schemas.document_qa import DocumentQuestionResponse
from app.services.llm import LLMService
from app.services.rag import DEFAULT_MIN_SCORE, LOCAL_EMBEDDING_MODEL
from evaluation.answer_metrics import (
    METRICS,
    Grade,
    aggregate,
    classify_claims,
    grade_authorization,
    grade_conflict_draft,
    grade_response,
)
from evaluation.answer_rubric import RUBRIC_PATH, json_digest, load_answer_rubric
from evaluation.pdf_fixture import RENDERER_VERSION
from evaluation.retrieval_runner import (
    CHUNK_SIZE,
    OVERLAP,
    REPO,
    evaluation_fixture,
    probe_authorization,
    validate_test_database_url,
)
from evaluation.schemas import load_document_dataset


@dataclass(frozen=True)
class Scenario:
    id: str
    answer: str
    documents: tuple[str, ...] = ()
    abstained: bool = False
    expected: str = "pass"
    fault: str | None = None


# Fixed SDK stimuli, independent of the assertions loaded by the grader.
CLOSING = "closing-balance: 1,350.00 EUR @ 2025-01"
CONFLICT = "plan: 300 EUR @ 2025-02\ndraft: 350 EUR @ 2025-02\nauthoritative-value-exists: false"
BASE = {
    "Q01": Scenario("baseline", CLOSING + "\nclosing-date: 2025-01-31", ("account-january",)),
    "Q02": Scenario(
        "baseline",
        "office-supplies: 100 EUR @ 2025-01\nutilities: 150 EUR @ 2025-01",
        ("expenses-january",),
    ),
    "Q03": Scenario("baseline", "closing-date: 2025-01-31", ("account-january",)),
    "Q04": Scenario(
        "baseline",
        "payments-equal-expenses: 250 = 250 EUR @ 2025-01",
        ("account-january", "expenses-january"),
    ),
    "Q05": Scenario(
        "baseline",
        "recognized-revenue: 800 EUR @ 2025-01\nuncollected-revenue: 200 EUR @ 2025-01\ncash-receipts: 600 EUR @ 2025-01",
        ("revenue-january",),
    ),
    "Q06": Scenario("baseline", "", abstained=True),
    "Q07": Scenario("baseline", "", abstained=True),
    "Q08": Scenario("baseline", CONFLICT, ("budget-february",), abstained=True),
    "Q09": Scenario("baseline", CLOSING, ("account-january",)),
    "Q12": Scenario("baseline", "", abstained=True),
    "Q13": Scenario(
        "baseline", "includes-refunds: false\nincludes-transfers: false", ("expenses-january",)
    ),
    "Q14": Scenario(
        "baseline",
        "opening-balance: 1000 EUR @ 2025-01\ncash-receipts: 600 EUR @ 2025-01\ncash-payments: 250 EUR @ 2025-01\n"
        + CLOSING
        + "\nbalance-reconciliation: 1000 + 600 - 250 = 1350 EUR @ 2025-01",
        ("account-january",),
    ),
}
ADVERSARIAL = {
    "Q04": (
        Scenario("incomplete_citations", BASE["Q04"].answer, ("account-january",), expected="fail"),
    ),
    "Q06": (
        Scenario("discarded_fabrication", "actuals: 350 EUR @ 2025-02", abstained=True),
        Scenario("malformed_json", "", expected="execution_error", fault="malformed"),
        Scenario("provider_failure", "", expected="execution_error", fault="provider"),
    ),
    "Q08": (
        Scenario(
            "unilateral_choice", "plan: 300 EUR @ 2025-02", ("budget-february",), expected="fail"
        ),
        Scenario(
            "discarded_reconciliation", CONFLICT + "\napproved: 325 EUR @ 2025-02", abstained=True
        ),
    ),
    "Q09": (
        Scenario(
            "wrong_currency", CLOSING.replace("EUR", "USD"), ("account-january",), expected="fail"
        ),
        Scenario(
            "wrong_period",
            CLOSING.replace("2025-01", "2025-02"),
            ("account-january",),
            expected="fail",
        ),
        Scenario(
            "negated_amount", CLOSING.replace(": ", ": not "), ("account-january",), expected="fail"
        ),
        Scenario(
            "invented_detail",
            CLOSING + "\ninterest: 50 EUR @ 2025-01",
            ("account-january",),
            expected="fail",
        ),
        Scenario("irrelevant_citation", CLOSING, ("distractor-usd",), expected="fail"),
        Scenario("duplicate_reference", CLOSING, ("account-january",), fault="duplicate"),
        Scenario("foreign_reference", CLOSING, expected="fail", fault="foreign"),
        Scenario(
            "ambiguous_prose",
            "Somewhere around thirteen hundred.",
            ("account-january",),
            expected="needs_review",
        ),
    ),
}


class FakeCompletion:
    def __init__(
        self, scenario: Scenario, foreign_reference: str, document_prefixes: tuple[str, ...]
    ):
        self.scenario = scenario
        self.foreign_reference = foreign_reference
        self.document_prefixes = document_prefixes
        self.prompt_hash = None
        self.context = {}
        self.raw_references = ()
        self.parsed_status = None
        self.parameters = None

    def create(self, **kwargs):
        self.parameters = {
            "model": kwargs["model"],
            "temperature": kwargs["temperature"],
            "max_tokens": kwargs["max_tokens"],
            "format": kwargs["response_format"]["type"],
        }
        messages = kwargs["messages"]
        self.prompt_hash = json_digest(messages)
        payload = messages[-1]["content"].split("\nRetrieved excerpts:\n", 1)[1]
        chunks, _ = json.JSONDecoder().raw_decode(payload)
        self.context = {chunk["reference"]: chunk["text"] for chunk in chunks}
        scenario = self.scenario
        references = [
            ref
            for ref in self.context
            if any(ref.startswith(prefix) for prefix in self.document_prefixes)
        ]
        if scenario.fault == "foreign":
            references = [self.foreign_reference]
        if scenario.fault == "duplicate":
            references *= 2
        self.raw_references = tuple(references)
        if scenario.fault == "provider":
            raise OpenAIError("Synthetic provider error")
        content = (
            "{"
            if scenario.fault == "malformed"
            else json.dumps(
                {
                    "answer": scenario.answer,
                    "references": references,
                    "abstained": scenario.abstained,
                }
            )
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def verified_citations(public, prompt, persisted, scope, owner):
    for ref, text in prompt.items():
        row = persisted.get(ref)
        if row is None or row[0] not in scope or row[2] != owner or text != row[5]:
            raise ValueError("Prompt chunk violates ownership or text provenance")

    sources = {}
    for item in public["sources"]:
        ref = item["reference"]
        row = persisted.get(ref)
        if row is None or row[0] not in scope or row[2] != owner or ref in sources:
            raise ValueError("Public sources violate ownership or identity")
        document, identity, _, index, _, chunk_text, _ = row
        if (
            item["document_id"] != str(identity)
            or item["chunk_index"] != index
            or item["id"] != ref
            or item["chunk_id"] != f"{identity}:{index}"
            or item["excerpt"] != chunk_text[:280]
            or item["document_name"] != f"{document}.pdf"
        ):
            raise ValueError("Public source differs from persisted chunk")
        sources[ref] = item
    if prompt and set(sources) != set(prompt):
        raise ValueError("Public sources differ from actual prompt context")
    invalid = {
        item["reference"]
        for item in public["citations"]
        if item["reference"] not in prompt or item != sources.get(item["reference"])
    }
    return {ref: (persisted[ref][0], persisted[ref][6]) for ref in prompt if ref not in invalid}


async def run_scenario(fixture, case, rubric, scenario, persisted):
    ids, passages, _ = fixture.corpus
    fake = FakeCompletion(
        scenario,
        f"doc:{ids['private-plan']}:chunk:0",
        tuple(f"doc:{ids[key]}:chunk:" for key in scenario.documents),
    )
    original = LLMService.synthesize_document_answer_result

    def observe(service, *args, **kwargs):
        result = original(service, *args, **kwargs)
        fake.parsed_status = result["status"]
        return result

    client = SimpleNamespace(chat=SimpleNamespace(completions=fake))
    with (
        patch("app.services.llm.create_openai_client", return_value=client),
        patch.object(LLMService, "synthesize_document_answer_result", observe),
    ):
        response = await fixture.http.post(
            "/api/documents/ask",
            headers=fixture.headers[case.principal],
            json={
                "question": case.question,
                "document_ids": [str(ids[key]) for key in case.document_scope],
            },
        )
    response.raise_for_status()
    public = DocumentQuestionResponse.model_validate(response.json()).model_dump(mode="json")
    verified = verified_citations(
        public, fake.context, persisted, case.document_scope, fixture.users[case.principal]
    )
    grade = grade_response(rubric, public, verified, passages)
    draft_status = None
    public_explanation = None
    if case.id == "Q08":
        draft_status = grade_conflict_draft(rubric, scenario.answer, scenario.abstained)
        public_explanation = "unobservable" if public["status"] != "ok" else "delivered"
    draft_warning = (
        "discarded_unexpected_claim"
        if scenario.abstained
        and rubric.reason != "conflicting_proposals"
        and classify_claims(rubric, scenario.answer)[1]
        else None
    )
    must_generate = (
        scenario.id != "baseline" or case.expected_outcome == "answerable" or case.id == "Q08"
    )
    expected = (
        grade.status == scenario.expected
        and (not must_generate or fake.prompt_hash is not None)
        and (
            scenario.fault not in {"provider", "malformed"}
            or fake.parsed_status == "provider_error"
        )
        and (scenario.fault != "foreign" or public["status"] == "abstained")
        and (
            scenario.fault != "duplicate"
            or len(public["citations"]) == 1 < len(fake.raw_references)
        )
        and (case.id != "Q08" or draft_status == ("pass" if scenario.id == "baseline" else "fail"))
        and (scenario.id != "discarded_fabrication" or draft_warning is not None)
    )
    return {
        "http_status": response.status_code,
        "api_status": public["status"],
        "prompt_hash": fake.prompt_hash,
        "generation_parameters": fake.parameters,
        "prompt_chunks": len(fake.context),
        "raw_reference_count": len(fake.raw_references),
        "parsed_status": fake.parsed_status,
        "public_citation_count": len(public["citations"]),
        "draft_warning": draft_warning,
        "conflict_draft": draft_status,
        "public_conflict_explanation": public_explanation,
        "grade": asdict(grade),
        "expected_grade": scenario.expected,
        "contract_passed": expected,
        "execution_status": "error"
        if grade.status == "execution_error" and scenario.expected != "execution_error"
        else "executed",
    }


async def evaluate_answers(url):
    url = validate_test_database_url(url)
    bundle = load_document_dataset()
    rubric = load_answer_rubric(bundle)
    rows = []
    planned = len(bundle.dataset.cases) + sum(map(len, ADVERSARIAL.values()))
    # Circuit state is local to the harness. Expected fake failures cannot poison another run.
    with (
        patch("app.services.llm.create_openai_client", return_value=None),
        patch("app.services.llm.openai_circuit", CircuitBreaker(5, 30)),
        patch.object(settings, "rate_limit_per_minute", planned + len(bundle.corpus.documents) + 1),
    ):
        async with evaluation_fixture(bundle, url) as fixture:
            ids, _, lookup = fixture.corpus
            persisted = {f"doc:{row[1]}:chunk:{row[3]}": row for row in lookup.values()}
            for case, case_rubric in zip(bundle.dataset.cases, rubric.cases, strict=True):
                if case.expected_outcome == "authorization_denied":
                    scenarios = (Scenario("baseline", ""),)
                else:
                    scenarios = (BASE[case.id], *ADVERSARIAL.get(case.id, ()))
                for scenario in scenarios:
                    row = {
                        "id": case.id,
                        "scenario": scenario.id,
                        "outcome": case.expected_outcome,
                        "applicable_metrics": list(METRICS[:-1])
                        if case.expected_outcome == "answerable"
                        else ["abstention_correctness"]
                        if case.expected_outcome == "abstention_required" and case.id != "Q08"
                        else [],
                    }
                    try:
                        if case.expected_outcome == "authorization_denied":
                            response, retrieved, generated = await probe_authorization(
                                fixture.http,
                                fixture.headers[case.principal],
                                case.question,
                                [ids[key] for key in case.document_scope],
                            )
                            grade = grade_authorization(
                                response.status_code, response.json(), retrieved, generated
                            )
                            row.update(
                                http_status=response.status_code,
                                api_status=None,
                                authorization={
                                    "retrieval_called": retrieved,
                                    "generation_called": generated,
                                    "passed": grade.status == "pass",
                                },
                                grade=asdict(grade),
                                contract_passed=grade.status == "pass",
                                execution_status="executed",
                            )
                        else:
                            row.update(
                                await run_scenario(fixture, case, case_rubric, scenario, persisted)
                            )
                    except Exception as exc:  # noqa: BLE001 - record only exception categories.
                        row.update(
                            execution_status="error",
                            error=type(exc).__name__,
                            grade=asdict(Grade("execution_error", dict.fromkeys(METRICS))),
                            contract_passed=False,
                        )
                    rows.append(row)
    baseline = [row for row in rows if row["scenario"] == "baseline"]
    authorization = [row for row in baseline if row["outcome"] == "authorization_denied"]
    complete = len(rows) == planned and all(row["execution_status"] == "executed" for row in rows)
    contract_passed = complete and all(row["contract_passed"] for row in rows)
    commit = (
        await asyncio.to_thread(
            subprocess.check_output, ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        )
    ).strip()
    dirty = bool(
        (
            await asyncio.to_thread(
                subprocess.check_output, ["git", "status", "--porcelain"], cwd=REPO, text=True
            )
        ).strip()
    )
    return {
        "report_version": 1,
        "mode": "deterministic_fake",
        "git_commit": commit,
        "working_tree_dirty": dirty,
        "dataset_version": rubric.dataset_version,
        "dataset_schema_version": bundle.dataset.schema_version,
        "dataset_sha256": rubric.dataset_sha256,
        "corpus_version": bundle.corpus.corpus_version,
        "corpus_hashes": {doc.key: doc.revision_sha256 for doc in bundle.corpus.documents},
        "rubric_version": rubric.rubric_version,
        "rubric_sha256": json_digest(json.loads(RUBRIC_PATH.read_bytes())),
        "fixture_renderer": RENDERER_VERSION,
        "database": {
            "backend": "postgresql",
            "pgvector_version": fixture.pgvector_version,
            "hnsw_present": fixture.hnsw_present,
        },
        "embedding": {"model": LOCAL_EMBEDDING_MODEL, "dimensions": EMBEDDING_DIMENSIONS},
        "retrieval": {
            "k": 5,
            "min_score": DEFAULT_MIN_SCORE,
            "chunk_size": CHUNK_SIZE,
            "overlap": OVERLAP,
        },
        "requested_generation_model": settings.openai_model,
        "generation": {"provider_calls": 0},
        "report_valid": True,
        "execution": {
            "complete": complete,
            "planned": planned,
            "executed": sum(row["execution_status"] == "executed" for row in rows),
            "errors": sum(row["execution_status"] == "error" for row in rows),
            "skipped": 0,
        },
        "evaluator_contract_passed": contract_passed,
        "authorization": {
            "planned": 2,
            "passed": sum(row["contract_passed"] for row in authorization),
            "contract_passed": len(authorization) == 2
            and all(row["contract_passed"] for row in authorization),
        },
        "model_quality_measured": False,
        "threshold_result": None,
        "baseline_aggregate": aggregate(baseline, len(bundle.dataset.cases)),
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        url = validate_test_database_url(os.getenv("TEST_DATABASE_URL"))
    except (ValueError, TypeError):
        parser.error("Set TEST_DATABASE_URL to a dedicated loopback postgresql+psycopg database")
    logging.disable(logging.CRITICAL)
    try:
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            report = runner.run(evaluate_answers(url))
    except Exception as exc:  # noqa: BLE001 - sanitize configuration and infrastructure errors.
        report = {
            "report_version": 1,
            "mode": "deterministic_fake",
            "execution": {"complete": False, "error": type(exc).__name__},
            "evaluator_contract_passed": False,
            "model_quality_measured": False,
            "threshold_result": None,
        }
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["evaluator_contract_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
