"""Retrieval metrics over half-open spans in document-local token coordinates."""

from collections.abc import Sequence

from evaluation.evidence_mapping import EvidenceKey, Span

METRICS = (
    "evidence_recall",
    "evidence_coverage",
    "chunk_precision",
    "novel_evidence_precision",
    "mrr",
)


def score_at_k(
    ranked: Sequence[tuple[str, Span]], evidence: dict[EvidenceKey, Span], k: int
) -> dict[str, float | None]:
    if k < 1:
        raise ValueError("k must be positive")
    if not evidence:
        return dict.fromkeys(METRICS)
    covered: dict[EvidenceKey, set[int]] = {key: set() for key in evidence}
    credited: set[EvidenceKey] = set()
    relevant = novel = first = 0
    for rank, (document, (start, end)) in enumerate(ranked[:k], start=1):
        hit = False
        complete = set()
        for key, (left, right) in evidence.items():
            if key[0] != document or max(left, start) >= min(right, end):
                continue
            hit = True
            covered[key].update(range(max(left, start), min(right, end)))
            if start <= left and right <= end:
                complete.add(key)
        if hit:
            relevant += 1
            first = first or rank
        if complete - credited:
            novel += 1
            credited.update(complete)
    fractions = [len(covered[key]) / (right - left) for key, (left, right) in evidence.items()]
    return {
        "evidence_recall": fractions.count(1.0) / len(evidence),
        "evidence_coverage": sum(fractions) / len(evidence),
        "chunk_precision": relevant / k,
        "novel_evidence_precision": novel / k,
        "mrr": 1 / first if first else 0.0,
    }
