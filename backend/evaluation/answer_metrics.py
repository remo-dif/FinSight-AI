"""Grade controlled facts and independently verify evidence coverage."""

from dataclasses import dataclass
from typing import Literal

from evaluation.answer_rubric import CaseRubric, parse_value
from evaluation.evidence_mapping import EvidenceKey, Span

Status = Literal["pass", "fail", "needs_review", "not_applicable", "execution_error"]
SAFE_ABSTENTIONS = {
    "I could not find enough relevant evidence in the authorized documents to answer that confidently.",
    "I could not find enough supporting evidence in the selected documents to answer.",
    "I could not validate references for an evidence-backed answer, so I am abstaining.",
}
METRICS = (
    "answer_correctness",
    "required_fact_completeness",
    "citation_presence",
    "citation_validity",
    "citation_precision",
    "claim_support",
    "citation_completeness",
    "abstention_correctness",
)


@dataclass(frozen=True)
class Grade:
    status: Status
    metrics: dict[str, float | None]
    reasons: tuple[str, ...] = ()


def classify_claims(rubric: CaseRubric, answer: str) -> tuple[set[str], int, bool]:
    """Accept only newline-separated fixture assertions with known fact identifiers."""
    facts = {fact.id: fact for fact in rubric.facts}
    correct = set()
    wrong = set()
    review = False
    for line in answer.splitlines():
        if not line.strip():
            continue
        key, separator, value = line.strip().partition(": ")
        if not separator:
            review = True
            continue
        fact = facts.get(key)
        if fact is None:
            for kind in ("money", "date", "boolean", "equation"):
                try:
                    parse_value(kind, value)
                except ValueError:
                    continue
                wrong.add(line.strip())
                break
            else:
                review = True
            continue
        if value.startswith("not "):
            value = value.removeprefix("not ")
            negated = True
        else:
            negated = False
        try:
            parsed = parse_value(fact.kind, value)
        except ValueError:
            review = True
            continue
        expected = parse_value(fact.kind, fact.value)
        if not negated and parsed == expected:
            correct.add(key)
        else:
            wrong.add((key, parsed, negated))
    return correct, len(wrong), review


def grade_authorization(
    http_status: int, body, retrieval_called: bool, generation_called: bool
) -> Grade:
    passed = (
        http_status == 404
        and body == {"detail": "Document not found"}
        and not retrieval_called
        and not generation_called
    )
    return Grade("pass" if passed else "fail", {}, () if passed else ("authorization_contract",))


def grade_conflict_draft(rubric: CaseRubric, draft: str, abstained: bool) -> Status:
    correct, wrong, review = classify_claims(rubric, draft)
    if wrong or not abstained:
        return "fail"
    if review:
        return "needs_review"
    return "pass" if all(fact.id in correct for fact in rubric.facts if fact.required) else "fail"


def grade_response(
    rubric: CaseRubric,
    response: dict,
    verified: dict[str, tuple[str, Span]],
    passages: dict[EvidenceKey, Span],
) -> Grade:
    metrics: dict[str, float | None] = dict.fromkeys(METRICS)
    status = response.get("status")
    if status not in {"ok", "abstained", "insufficient_evidence", "extractive_preview"}:
        return Grade("execution_error", metrics, ("generation_or_response_error",))
    if rubric.outcome == "authorization_denied":
        return Grade("not_applicable", metrics)
    citations = {item["reference"] for item in response["citations"]}
    if rubric.outcome == "abstention_required":
        passed = (
            status in {"abstained", "insufficient_evidence"}
            and response["abstained"]
            and not citations
            and response["answer"] in SAFE_ABSTENTIONS
        )
        metrics["abstention_correctness"] = float(passed)
        return Grade(
            "pass" if passed else "fail", metrics, () if passed else ("public_abstention",)
        )

    correct, wrong, review = (
        classify_claims(rubric, response["answer"]) if status == "ok" else (set(), 0, False)
    )
    required = {fact.id for fact in rubric.facts if fact.required}
    metrics["required_fact_completeness"] = len(correct & required) / len(required)
    metrics["citation_presence"] = float(bool(citations))
    valid = citations & verified.keys()
    metrics["citation_validity"] = len(valid) / len(citations) if citations else None

    supported = set()
    contributing = set()
    for fact in rubric.facts:
        if fact.id not in correct:
            continue
        for group in fact.support:
            group_contributors = set()
            for reference in group:
                key = reference.document_key, reference.evidence_key
                left, right = passages[key]
                covered = set()
                for citation in valid:
                    document, (start, end) = verified[citation]
                    if document == key[0] and max(left, start) < min(right, end):
                        covered.update(range(max(left, start), min(right, end)))
                        group_contributors.add(citation)
                if len(covered) != right - left:
                    break
            else:
                supported.add(fact.id)
                contributing.update(group_contributors)
    if citations:
        metrics["citation_precision"] = len(contributing) / len(citations)
    if not review and (correct or wrong):
        metrics["claim_support"] = len(supported) / (len(correct) + wrong)
    metrics["citation_completeness"] = len(required & supported) / len(required)

    if review:
        for name in ("required_fact_completeness", "citation_precision", "citation_completeness"):
            metrics[name] = None

    if wrong or status != "ok" or (not review and not required <= correct):
        metrics["answer_correctness"] = 0.0
    elif not review:
        metrics["answer_correctness"] = 1.0
    if metrics["answer_correctness"] == 0 or citations != valid:
        return Grade("fail", metrics, ("incorrect_answer_or_invalid_reference",))
    if review:
        return Grade("needs_review", metrics, ("unsupported_prose",))
    if metrics["citation_completeness"] != 1 or metrics["citation_precision"] != 1:
        return Grade("fail", metrics, ("incomplete_citation_support",))
    return Grade("pass", metrics)


def aggregate(rows: list[dict], planned: int) -> dict:
    statuses = ("pass", "fail", "needs_review", "not_applicable", "execution_error", "skipped")
    counts = {status: sum(row["grade"]["status"] == status for row in rows) for status in statuses}
    metrics = {}
    for name in METRICS:
        applicable = [row for row in rows if name in row["applicable_metrics"]]
        values = [row["grade"]["metrics"][name] for row in applicable]
        measured = [value for value in values if value is not None]
        metrics[name] = {
            "applicable": len(values),
            "evaluated": len(measured),
            "mean": sum(measured) / len(values)
            if values and len(measured) == len(values) and len(rows) == planned
            else None,
        }
    return {
        "planned": planned,
        "executed": len(rows) - counts["skipped"],
        **counts,
        "metrics": metrics,
    }
