"""Offline contracts for the real-model evaluation. No application imports."""

import hashlib
import json
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from evaluation.answer_rubric import RUBRIC_PATH, load_answer_rubric
from evaluation.schemas import DATA_DIRECTORY, load_document_dataset

ORIGIN = "https://api.openai.com"
LOCAL_MODEL = "deterministic-local-hash-v2"
ModelName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")]
Price = Annotated[Decimal, Field(gt=0, max_digits=16, decimal_places=8)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Profile(Contract):
    schema_version: Literal[1]
    origin: Literal["https://api.openai.com"]
    model: ModelName
    embedding_backend: Literal["local", "openai"]
    embedding_model: ModelName
    input_per_million: Price
    output_per_million: Price
    embedding_per_million: Price | None = None
    pricing_source: Literal["https://openai.com/api/pricing/"]
    pricing_date: Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    repetitions: int = Field(default=5, ge=1, le=20)
    limit: int = Field(default=5, ge=1, le=10)
    min_score: float = Field(default=0.05, ge=0.05, le=1)
    timeout_seconds: float = Field(default=30, gt=0, le=120)

    @model_validator(mode="after")
    def check_embedding(self):
        if self.embedding_backend == "local":
            if self.embedding_model != LOCAL_MODEL or self.embedding_per_million is not None:
                raise ValueError("Local embedding profile must use the fixed local model")
        elif not self.embedding_model.startswith("text-embedding-3-") or (
            self.embedding_per_million is None
        ):
            raise ValueError("Supply a supported remote embedding model and its tariff")
        return self


class Budget(Contract):
    requests: int = Field(gt=0)
    tokens: int = Field(gt=0)
    estimated_cost: Price


def canonical(value) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def plan_for(profile: Profile) -> dict:
    bundle = load_document_dataset()
    load_answer_rubric(bundle)
    cases = [
        {"case": case.id, "repetition": repetition}
        for case in bundle.dataset.cases
        for repetition in range(
            1, 2 if case.expected_outcome == "authorization_denied" else profile.repetitions + 1
        )
    ]
    authorized = (
        sum(case.expected_outcome != "authorization_denied" for case in bundle.dataset.cases)
        * profile.repetitions
    )
    embedding = (
        len(bundle.corpus.documents) + authorized if profile.embedding_backend == "openai" else 0
    )
    # Generous framing bound using the complete synthetic corpus, including
    # JSON escaping and chunk overlap. The transport rechecks actual payloads.
    corpus_bytes = sum(
        len((DATA_DIRECTORY / "corpus" / doc.path).read_bytes()) for doc in bundle.corpus.documents
    )
    input_bound = 4096 + 12 * corpus_bytes
    output_bound = authorized * 450
    input_tokens = authorized * input_bound
    embedding_tokens = embedding * input_bound
    cost = (
        input_tokens * profile.input_per_million
        + output_bound * profile.output_per_million
        + embedding_tokens * (profile.embedding_per_million or Decimal(0))
    ) / 1_000_000
    return {
        "schema_version": 1,
        "planning_token_reservation": input_tokens + output_bound + embedding_tokens,
        "planning_cost_reservation": str(cost),
        "profile_sha256": digest(profile.model_dump(mode="json")),
        "dataset_sha256": hashlib.sha256(
            (DATA_DIRECTORY / "document_qa_v1.json").read_bytes()
        ).hexdigest(),
        "rubric_sha256": hashlib.sha256(RUBRIC_PATH.read_bytes()).hexdigest(),
        "corpus": {doc.key: doc.revision_sha256 for doc in bundle.corpus.documents},
        "units": cases,
        "request_upper_bound": authorized + embedding,
    }
