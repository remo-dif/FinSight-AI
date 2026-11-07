"""Independent dimensions for real-model observations and optional human review."""

from typing import Literal

from evaluation.answer_metrics import classify_claims, grade_authorization, grade_response
from evaluation.real_model_contract import Contract
from evaluation.retrieval_metrics import score_at_k


class Adjudication(Contract):
    schema_version: Literal[1]
    observation_sha256: str
    rubric_sha256: str
    dimension: str
    verdict: Literal["pass", "fail", "needs_review"]
    reviewer: str
    reason: str


def grade(observation, rubric, passages, limit):
    rows = observation["ranking"]
    gold = {key: span for key, span in passages.items()}
    scores = (
        score_at_k([(row["document"], tuple(row["span"])) for row in rows], gold, limit)
        if gold
        else None
    )
    public = observation["public"]
    result = {
        "schema_version": 1,
        "retrieval_metrics": scores,
        "retrieval_sufficiency": ("pass" if scores["evidence_recall"] == 1 else "fail")
        if scores
        else "not_applicable",
        "operational_reliability": "fail" if observation["error"] else "pass",
        "authorization": "not_applicable",
        "factual_correctness": "not_applicable",
        "required_fact_coverage": None,
        "required_causal_relationship": "not_applicable",
        "citation_validity": "not_applicable",
        "citation_support": "not_applicable",
        "abstention": "not_applicable",
        "conflict": "not_applicable",
    }
    if rubric.outcome == "authorization_denied":
        result["authorization"] = grade_authorization(
            observation["http_status"],
            public,
            observation["retrieval_called"],
            bool(observation["provider_attempts"]),
        ).status
        return result
    if observation["error"]:
        return result

    citations = {item["reference"] for item in public["citations"]}
    verified = {
        ref: (item[0], tuple(item[1])) for ref, item in observation["verified_citations"].items()
    }
    raw = observation["parsed_draft"]
    invalid_raw = raw is not None and any(
        reference not in observation["prompt_references"] for reference in raw["references"]
    )
    if invalid_raw or citations - verified.keys() or (public["status"] == "ok" and not citations):
        result["citation_validity"] = "fail"
    elif citations or (raw is not None and raw["references"]):
        result["citation_validity"] = "pass"

    if rubric.outcome == "abstention_required":
        safe = grade_response(rubric, public, verified, gold)
        result["abstention"] = "fail" if invalid_raw else safe.status
        if raw is not None and raw["abstained"] and raw["answer"].strip() and not invalid_raw:
            result["abstention"] = "needs_review"
        if rubric.reason == "conflicting_proposals" and scores and scores["evidence_recall"] == 1:
            if raw is None or not raw["abstained"]:
                result["conflict"] = "fail"
            else:
                correct, wrong, review = classify_claims(rubric, raw["answer"])
                required = {fact.id for fact in rubric.facts if fact.required}
                result["conflict"] = (
                    "fail"
                    if wrong or not raw["answer"].strip()
                    else "needs_review"
                    if review
                    else "pass"
                    if required <= correct
                    else "fail"
                )
        return result

    if public["status"] != "ok":
        result["abstention"] = "fail"
        result["factual_correctness"] = "fail"
        result["required_fact_coverage"] = 0.0
        return result
    correct, wrong, review = classify_claims(rubric, public["answer"])
    required = {fact.id for fact in rubric.facts if fact.required}
    relationships = {
        fact.id for fact in rubric.facts if fact.required and fact.kind == "relationship"
    }
    if relationships:
        result["required_causal_relationship"] = (
            "pass"
            if relationships <= correct and not wrong and not review
            else "needs_review"
            if review and not wrong
            else "fail"
        )
    result["factual_correctness"] = (
        "fail" if wrong else "needs_review" if review else ("pass" if correct else "fail")
    )
    result["required_fact_coverage"] = None if review else len(required & correct) / len(required)
    if citations:
        # Independently check whether any annotated evidence is present, even
        # when free-form output requires semantic review.
        cited_scores = score_at_k(list(verified.values()), gold, len(citations)) if gold else None
        metrics = grade_response(rubric, public, verified, gold).metrics
        result["citation_support"] = (
            "fail"
            if cited_scores and cited_scores["evidence_coverage"] == 0
            else "needs_review"
            if review
            else "pass"
            if metrics["claim_support"] == 1 and metrics["citation_completeness"] == 1
            else "fail"
        )
    return result
