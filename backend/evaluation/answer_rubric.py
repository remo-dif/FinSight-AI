"""Versioned annotations for controlled document-answer evaluation."""

import json
import re
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from evaluation.schemas import (
    DATA_DIRECTORY,
    AnnotationModel,
    EvaluationBundle,
    EvidenceReference,
    Key,
)

RUBRIC_PATH = DATA_DIRECTORY / "document_answer_rubric_v1.json"
PERIOD = r"[0-9]{4}-(?:0[1-9]|1[0-2])"
NUMBER = r"-?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?"


def json_digest(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(encoded.encode("ascii")).hexdigest()


def parse_value(kind: str, text: str):
    """Parse only the documented fixture grammar, with no inference from prose."""
    if kind == "relationship":
        match = re.fullmatch(r"([a-z][a-z0-9-]*) explains ([a-z][a-z0-9-]*)", text)
        if not match:
            raise ValueError("Expected explicit cause explains effect")
        return match.groups()
    if kind == "date":
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", text):
            raise ValueError("Expected ISO date")
        return date.fromisoformat(text)
    if kind == "boolean":
        if text not in {"true", "false"}:
            raise ValueError("Expected explicit polarity")
        return text == "true"
    number = NUMBER if kind == "money" else rf"{NUMBER}(?: [+-] {NUMBER})* = {NUMBER}"
    match = re.fullmatch(rf"({number}) ([A-Z]{{3}}) @ ({PERIOD})", text)
    if not match:
        raise ValueError("Expected amount or equation, currency and period")
    expression, currency, period = match.groups()
    if kind == "money":
        return Decimal(expression.replace(",", "")), currency, period
    values = tuple(
        token if token in {"+", "-", "="} else Decimal(token.replace(",", ""))
        for token in expression.split()
    )
    return values, currency, period


class Fact(AnnotationModel):
    id: Key
    kind: Literal["money", "date", "boolean", "equation", "relationship"]
    value: str
    required: bool = True
    support: list[list[EvidenceReference]] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_fact(self) -> Self:
        try:
            parsed = parse_value(self.kind, self.value)
        except ValueError as exc:
            raise ValueError(f"Invalid value for fact {self.id}") from exc
        if self.kind in {"money", "equation"} and parsed[1] not in {"EUR", "USD"}:
            raise ValueError(f"Unsupported currency for fact {self.id}")
        if self.kind == "equation":
            values = parsed[0]
            total = values[0]
            for operator, operand in zip(values[1:-2:2], values[2:-2:2], strict=True):
                total = total + operand if operator == "+" else total - operand
            if total != values[-1]:
                raise ValueError(f"Inconsistent equation for fact {self.id}")
        groups = [
            frozenset((ref.document_key, ref.evidence_key) for ref in group)
            for group in self.support
        ]
        if any(
            not group or len(group) != len(refs)
            for group, refs in zip(groups, self.support, strict=True)
        ):
            raise ValueError(f"Empty or repeated support references for fact {self.id}")
        if len(set(groups)) != len(groups):
            raise ValueError(f"Duplicate support group for fact {self.id}")
        return self


class CaseRubric(AnnotationModel):
    id: str
    outcome: Literal["answerable", "abstention_required", "authorization_denied"]
    facts: list[Fact]
    reason: (
        Literal["missing_actuals", "ambiguous_account", "conflicting_proposals", "missing_fx"]
        | None
    )
    expected_http_status: Literal[200, 404]


class AnswerRubric(AnnotationModel):
    rubric_version: Literal["1.1.0"]
    dataset_version: str
    dataset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    cases: list[CaseRubric]


def load_answer_rubric(bundle: EvaluationBundle, path: Path = RUBRIC_PATH) -> AnswerRubric:
    rubric = AnswerRubric.model_validate_json(path.read_bytes())
    dataset = bundle.dataset.model_dump(mode="json")
    if (
        rubric.dataset_version != bundle.dataset.dataset_version
        or rubric.dataset_sha256 != json_digest(dataset)
    ):
        raise ValueError("Rubric does not match the version and canonical digest of the dataset")
    cases = {case.id: case for case in bundle.dataset.cases}
    if [case.id for case in rubric.cases] != list(cases):
        raise ValueError("Rubric must cover every dataset case exactly once in dataset order")
    for row in rubric.cases:
        case = cases[row.id]
        if (row.outcome, row.expected_http_status) != (
            case.expected_outcome,
            case.expected_http_status,
        ):
            raise ValueError(f"Unexpected outcome for {row.id}")
        if len({fact.id for fact in row.facts}) != len(row.facts):
            raise ValueError(f"Duplicate fact identifiers for {row.id}")
        needs_facts = row.outcome == "answerable" or row.reason == "conflicting_proposals"
        if needs_facts != any(fact.required for fact in row.facts) or (
            not needs_facts and row.facts
        ):
            raise ValueError(f"Unexpected required facts for {row.id}")
        reasons = {
            "ambiguous": {"ambiguous_account"},
            "conflicting": {"conflicting_proposals"},
            "insufficient_evidence": {"missing_actuals", "missing_fx"},
        }
        if row.reason not in reasons.get(case.answerability, {None}):
            raise ValueError(f"Unexpected abstention reason for {row.id}")
        eligible = {(ref.document_key, ref.evidence_key) for ref in case.relevant_evidence}
        for fact in row.facts:
            if any(
                (ref.document_key, ref.evidence_key) not in eligible
                for group in fact.support
                for ref in group
            ):
                raise ValueError(f"Invalid or unauthorized support for {row.id}/{fact.id}")
    return rubric
