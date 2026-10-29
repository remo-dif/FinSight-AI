"""Run reproducible local-hash retrieval and mocked financial-response evaluations.

Document Q&A is explicitly partial, not a passed answer-quality gate. No live
provider, customer database, pricing lookup or model-based judge is used.
"""

import argparse
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.agents.orchestrator import OrchestratorAgent
from app.agents.tools import FinanceToolLayer
from app.core.config import settings
from app.core.database import Base
from app.models.finance import Transaction
from app.models.user import User
from app.repositories.transactions import TransactionRepository
from app.services.analytics import FinanceAnalyticsService
from app.services.llm import LLMService
from app.services.rag import RagService

DATASET = Path(__file__).parent / "data" / "rag_cases.json"


def stable_id(kind: str, name: str):
    return uuid5(NAMESPACE_URL, f"finsight-synthetic-eval/{kind}/{name}")


def load_dataset(path: Path = DATASET) -> dict:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    ids = [case["id"] for case in dataset["cases"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate evaluation case IDs")
    for case in dataset["cases"]:
        for name in case["documents"]:
            if name not in dataset["documents"]:
                raise ValueError(f"Unknown document in {case['id']}")
        for name in case["records"]:
            if name not in dataset["records"]:
                raise ValueError(f"Unknown record in {case['id']}")
        if not set(case["relevant_sources"]) <= set(case["documents"]):
            raise ValueError(f"Invalid relevance annotation in {case['id']}")
    return dataset


def grade_case(dataset: dict, case: dict, state: dict, retrieved: list, prompts: list) -> dict:
    """Compare output to hand-authored expectations, not production analytics."""
    failures = []
    observed = {row.metadata["source"]["id"] for row in retrieved}
    expected = {str(stable_id("document", name)) for name in case["relevant_sources"]}
    authorized_documents = {
        str(stable_id("document", name))
        for name in case["documents"]
        if dataset["documents"][name]["owner"] == "a"
    }
    context_sources = {row.metadata["source"]["id"] for row in state.get("rag_results", [])}
    if not (observed | context_sources) <= authorized_documents:
        failures.append("unauthorized_document_in_retrieval_or_context")
    recall = len(observed & expected) / len(expected) if expected else None
    precision = len(observed & expected) / len(observed) if observed else None
    if expected - observed:
        failures.append("missing_relevant_sources_at_k")

    answer = state["final_answer"]
    for value in case.get("forbidden_elements", []) + ["SECRET_OTHER_USER_MARKER"]:
        if value.casefold() in answer.casefold():
            failures.append("forbidden_answer_element")
    if "ATTACK_DOCUMENT_MARKER" in json.dumps(prompts):
        failures.append("untrusted_document_entered_financial_claim_selector")

    evidence = state["tool_results"]["_evidence"]
    facts = {fact["key"]: fact for fact in evidence["facts"]}
    authorized_records = {
        str(stable_id("record", name))
        for name in case["records"]
        if dataset["records"][name].get("owner", "a") == "a"
    }
    references = [ref for fact in facts.values() for ref in fact["transaction_ids"]]
    if not set(references + evidence["source_transaction_ids"]) <= authorized_records:
        failures.append("unauthorized_transaction_reference")
    supported = 0
    annotations = case.get("expected_claims", {})
    for key, claim in annotations.items():
        actual = facts.get(key)
        expected_refs = {str(stable_id("record", name)) for name in claim["records"]}
        if (
            actual is not None
            and Decimal(actual["amount"]) == Decimal(claim["amount"])
            and actual["currency"] == case["currency"]
            and actual["period"] == case.get("expected_period", dataset["default_expected_period"])
            and set(actual["transaction_ids"]) == expected_refs
        ):
            supported += 1
        else:
            failures.append(f"unsupported_annotated_claim:{key}")
    if "expected_duplicates" in case:
        expected_duplicates = {
            str(stable_id("record", name)) for name in case["expected_duplicates"]
        }
        if set(state["tool_results"].get("suspected_duplicate_ids", [])) != expected_duplicates:
            failures.append("duplicate_reference_mismatch")

    missing = [value for value in case.get("required_elements", []) if value not in answer]
    abstained = "No matching financial facts" in answer or "need verifiable" in answer
    abstention_match = abstained == case["should_abstain"] if "should_abstain" in case else None
    partial = case.get("capability") == "document_qa"
    if not partial:
        failures.extend("missing_required_answer_element" for _ in missing)
        if abstention_match is False:
            failures.append("incorrect_abstention")
    return {
        "id": case["id"],
        "status": "failed" if failures else "partial" if partial else "passed",
        "failure_reasons": failures,
        "capability_gap": "document_qa_and_document_citations_not_implemented" if partial else None,
        "retrieved_source_ids": sorted(observed),
        "k": case.get("k", 5),
        "retrieval_recall_at_k": recall,
        "retrieval_precision_at_k": precision,
        "ownership_passed": (observed | context_sources) <= authorized_documents,
        "annotated_claims": len(annotations),
        "supported_annotated_claims": supported,
        "financial_reference_validity": (
            len([r for r in references if r in authorized_records]) / len(references)
        )
        if references
        else None,
        "required_elements_present": len(case.get("required_elements", [])) - len(missing),
        "required_elements_total": len(case.get("required_elements", [])),
        "answer_quality_evaluated": not partial,
        "annotated_claim_support": supported / len(annotations) if annotations else None,
        "answer_required_element_presence": (
            (len(case.get("required_elements", [])) - len(missing)) / len(case["required_elements"])
            if not partial and case.get("required_elements")
            else None
        ),
        "abstention_accuracy": abstention_match if not partial else None,
        "unsupported_claim_absence": (
            not any(value.casefold() in answer.casefold() for value in case["forbidden_elements"])
            if case.get("forbidden_elements")
            else None
        ),
        "observed_abstention_match": abstention_match,
        "document_citation_correctness": None,
    }


def evaluate_case(dataset: dict, case: dict) -> dict:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    prompts = []

    def complete(**kwargs):
        prompts.append(kwargs["messages"])
        content = case.get("provider_draft", kwargs["messages"][1]["content"])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
    try:
        with (
            Session(engine) as db,
            patch.object(settings, "embedding_backend", "local"),
            patch("app.services.llm.create_openai_client", return_value=client),
        ):
            for owner in ("a", "b"):
                db.add(
                    User(
                        id=stable_id("user", owner),
                        email=f"{owner}@example.invalid",
                        full_name="Synthetic evaluation",
                        password_hash="unused",
                    )
                )
            db.flush()
            rag = RagService(db)
            for name in case["documents"]:
                source = dataset["documents"][name]
                rag.index_text(
                    stable_id("user", source["owner"]),
                    "upload",
                    stable_id("document", name),
                    source["text"],
                )
            for name in case["records"]:
                row = dataset["records"][name]
                db.add(
                    Transaction(
                        id=stable_id("record", name),
                        user_id=stable_id("user", row.get("owner", "a")),
                        posted_at=date.fromisoformat(row["date"]),
                        amount=Decimal(row["amount"]),
                        merchant=row["merchant"],
                        description="Synthetic evaluation record",
                        category=row["category"],
                        currency=row["currency"],
                        source="synthetic",
                    )
                )
            db.commit()
            retrieved = rag.retrieve_chunks(
                stable_id("user", "a"), case["question"], case.get("k", 5)
            )
            tools = FinanceToolLayer(FinanceAnalyticsService(TransactionRepository(db)))
            state = OrchestratorAgent(tools, rag, LLMService()).run(
                {
                    "user_id": stable_id("user", "a"),
                    "message": case["question"],
                    "currency": case["currency"],
                    "release_database": db.rollback,
                }
            )
            return grade_case(dataset, case, state, retrieved, prompts)
    finally:
        engine.dispose()


def evaluate(dataset: dict | None = None) -> dict:
    dataset = dataset or load_dataset()
    results = []
    for case in dataset["cases"]:
        try:
            results.append(evaluate_case(dataset, case))
        except Exception as exc:  # noqa: BLE001 - keep every per-case failure visible, without input text
            # Exception messages may contain input data; expose only a safe category.
            results.append(
                {
                    "id": case["id"],
                    "status": "failed",
                    "failure_reasons": [f"evaluation_error:{type(exc).__name__}"],
                }
            )

    def mean(field, rows=None):
        values = [
            row[field] for row in (results if rows is None else rows) if row.get(field) is not None
        ]
        return {
            "value": sum(values) / len(values) if values else None,
            "evaluated_cases": len(values),
        }

    return {
        "dataset_version": dataset["version"],
        "environment": "sqlite-local-hash-mocked-llm",
        "total": len(results),
        **{
            status: sum(row["status"] == status for row in results)
            for status in ("passed", "failed", "partial")
        },
        "metrics": {
            field: mean(field)
            for field in (
                "retrieval_recall_at_k",
                "retrieval_precision_at_k",
                "financial_reference_validity",
                "annotated_claim_support",
                "answer_required_element_presence",
                "abstention_accuracy",
                "ownership_passed",
                "unsupported_claim_absence",
            )
        },
        "retrieval_by_k": {
            str(k): {
                field: mean(field, [row for row in results if row.get("k") == k])
                for field in ("retrieval_recall_at_k", "retrieval_precision_at_k")
            }
            for k in sorted({row["k"] for row in results if "k" in row})
        },
        "semantic_faithfulness": None,
        "document_citation_correctness": None,
        "cases": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Also fail on documented unsupported document-Q&A capabilities",
    )
    args = parser.parse_args()
    report = evaluate()
    serialized = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    print(
        f"AI/RAG: {report['total']} cases; {report['passed']} passed; "
        f"{report['failed']} failed; {report['partial']} partial (unsupported answer capability)",
        file=sys.stderr,
    )
    return int(bool(report["failed"] or (args.require_complete and report["partial"])))


if __name__ == "__main__":
    raise SystemExit(main())
