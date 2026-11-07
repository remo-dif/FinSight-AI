"""Align verified production chunk rows to normalized document token spans."""

from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256

Span = tuple[int, int]
EvidenceKey = tuple[str, str]


@dataclass(frozen=True)
class StoredChunk:
    index: int
    text: str
    digest: str


def map_evidence(extracted: str, anchors: dict[str, str]) -> dict[str, Span]:
    tokens = extracted.split()
    spans = {}
    for key, anchor in anchors.items():
        passage = anchor.split()
        if not passage:
            raise ValueError(f"Empty evidence anchor: {key}")
        starts = [
            i
            for i in range(len(tokens) - len(passage) + 1)
            if tokens[i : i + len(passage)] == passage
        ]
        if len(starts) != 1:
            raise ValueError(f"Missing or ambiguous evidence anchor: {key}")
        spans[key] = (starts[0], starts[0] + len(passage))
    return spans


def align_chunks(
    extracted: str, chunks: Sequence[StoredChunk], *, chunk_size: int, overlap: int
) -> dict[int, Span]:
    if not 0 <= overlap < chunk_size:
        raise ValueError("Invalid chunk geometry")
    tokens = extracted.split()
    spans = {}
    start = end = 0
    for index, chunk in enumerate(chunks):
        if chunk.index != index or (index and end == len(tokens)):
            raise ValueError("Missing, duplicate or unexpected chunk position")
        if sha256(chunk.text.encode("utf-8")).hexdigest() != chunk.digest:
            raise ValueError(f"Chunk hash mismatch: {index}")
        end = min(start + chunk_size, len(tokens))
        if end <= start or chunk.text != " ".join(tokens[start:end]):
            raise ValueError(f"Cannot align persisted chunk: {index}")
        spans[index] = (start, end)
        start = end - overlap
    if not spans or end != len(tokens):
        raise ValueError("Incomplete persisted chunk alignment")
    return spans
