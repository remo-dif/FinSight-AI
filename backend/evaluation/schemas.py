"""Offline document-Q&A annotations. Loading validates data, never runs AI services."""

import hashlib
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Key = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,79}$")]
Version = Annotated[str, StringConstraints(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]

DATA_DIRECTORY = Path(__file__).parent / "data"


class AnnotationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EvidencePassage(AnnotationModel):
    key: Key
    text: Text


class Document(AnnotationModel):
    key: Key
    owner: Key
    path: Text
    revision_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    evidence: list[EvidencePassage] = Field(min_length=1)


class CorpusManifest(AnnotationModel):
    schema_version: Literal[1]
    corpus_version: Version
    description: Text
    documents: list[Document] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_identifiers(self) -> Self:
        keys = [document.key for document in self.documents]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate document keys")
        paths = [document.path for document in self.documents]
        if len(paths) != len(set(paths)):
            raise ValueError("Duplicate document paths")
        for document in self.documents:
            evidence = [passage.key for passage in document.evidence]
            if len(evidence) != len(set(evidence)):
                raise ValueError(f"Duplicate evidence keys in {document.key}")
        return self


class EvidenceReference(AnnotationModel):
    document_key: Key
    evidence_key: Key


class Assertion(AnnotationModel):
    text: Text
    rationale: Text
    evidence: list[EvidenceReference]


class EvaluationCase(AnnotationModel):
    id: Annotated[str, StringConstraints(pattern=r"^Q[0-9]{2,4}$")]
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
    ]
    category: Literal[
        "factual",
        "amount_currency",
        "date_period",
        "multiple_documents",
        "terminology",
        "insufficient_evidence",
        "ambiguous",
        "conflicting_sources",
        "distractor",
        "unauthorized_scope",
        "unsupported_assertion",
    ]
    answerability: Literal[
        "answerable", "insufficient_evidence", "ambiguous", "conflicting", "unauthorized"
    ]
    principal: Key
    document_scope: list[Key] = Field(min_length=1, max_length=100)
    relevant_evidence: list[EvidenceReference]
    required_assertions: list[Assertion]
    forbidden_assertions: list[Assertion]
    expected_status: Literal["ok", "abstained", "authorization_denied"]
    expected_http_status: Literal[200, 404]
    expected_sources: list[Key]


class DocumentDataset(AnnotationModel):
    schema_version: Literal[1]
    dataset_version: Version
    corpus_version: Version
    description: Text
    cases: list[EvaluationCase] = Field(min_length=1)


class EvaluationBundle(AnnotationModel):
    """Cross-file integrity checks, independent of runtime database identities."""

    corpus: CorpusManifest
    dataset: DocumentDataset

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        if self.corpus.corpus_version != self.dataset.corpus_version:
            raise ValueError("Dataset and corpus versions differ")
        documents = {document.key: document for document in self.corpus.documents}
        passages = {
            (document.key, passage.key)
            for document in self.corpus.documents
            for passage in document.evidence
        }
        case_ids = [case.id for case in self.dataset.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Duplicate case IDs")
        for case in self.dataset.cases:
            scope = set(case.document_scope)
            if len(scope) != len(case.document_scope) or not scope <= documents.keys():
                raise ValueError(f"Invalid document scope in {case.id}")
            unauthorized = case.answerability == "unauthorized"
            foreign = {key for key in scope if documents[key].owner != case.principal}
            if bool(foreign) != unauthorized:
                raise ValueError(f"Invalid ownership for authorization scenario in {case.id}")
            if (case.category == "unauthorized_scope") != unauthorized:
                raise ValueError(f"Invalid authorization category in {case.id}")
            status = (
                "authorization_denied"
                if unauthorized
                else "ok"
                if case.answerability == "answerable"
                else "abstained"
            )
            if case.expected_status != status or case.expected_http_status != (
                404 if unauthorized else 200
            ):
                raise ValueError(f"Contradictory expected status in {case.id}")
            relevant = {(ref.document_key, ref.evidence_key) for ref in case.relevant_evidence}
            if len(relevant) != len(case.relevant_evidence):
                raise ValueError(f"Duplicate relevance references in {case.id}")
            assertions = case.required_assertions + case.forbidden_assertions
            references = case.relevant_evidence + [
                ref for assertion in assertions for ref in assertion.evidence
            ]
            for ref in references:
                pair = (ref.document_key, ref.evidence_key)
                if pair not in passages:
                    raise ValueError(f"Unknown evidence reference in {case.id}")
                if not unauthorized and ref.document_key not in scope:
                    raise ValueError(f"Evidence outside document scope in {case.id}")
            sources = set(case.expected_sources)
            relevant_documents = {key for key, _ in relevant}
            if (
                len(sources) != len(case.expected_sources)
                or not sources <= scope & relevant_documents
            ):
                raise ValueError(f"Inconsistent expected sources in {case.id}")
            if status == "ok":
                if not relevant or not case.required_assertions or sources != relevant_documents:
                    raise ValueError(f"Answerable case lacks evidence or assertions in {case.id}")
            elif sources or case.required_assertions:
                raise ValueError(
                    f"Non-answer case requires answer assertions or sources in {case.id}"
                )
            for assertion in case.required_assertions:
                refs = {(ref.document_key, ref.evidence_key) for ref in assertion.evidence}
                if not refs or not refs <= relevant:
                    raise ValueError(f"Required assertion lacks relevant evidence in {case.id}")
            required = {assertion.text.casefold() for assertion in case.required_assertions}
            forbidden = {assertion.text.casefold() for assertion in case.forbidden_assertions}
            if required & forbidden:
                raise ValueError(f"Contradictory assertions in {case.id}")
        return self


def load_document_dataset(data_directory: Path = DATA_DIRECTORY) -> EvaluationBundle:
    """Validate a local manifest, byte hashes, passages and cross-file references."""
    corpus_directory = (data_directory / "corpus").resolve()
    corpus = CorpusManifest.model_validate_json(
        (corpus_directory / "manifest.json").read_text(encoding="utf-8")
    )
    for document in corpus.documents:
        path = (corpus_directory / document.path).resolve()
        if not path.is_relative_to(corpus_directory) or path.suffix != ".txt":
            raise ValueError(f"Document path must remain inside corpus: {document.key}")
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != document.revision_sha256:
            raise ValueError(f"Content hash mismatch: {document.key}")
        content = payload.decode("utf-8")
        for passage in document.evidence:
            if content.count(passage.text) != 1:
                raise ValueError(
                    f"Evidence must identify one exact passage: {document.key}/{passage.key}"
                )
    dataset = DocumentDataset.model_validate_json(
        (data_directory / "document_qa_v1.json").read_text(encoding="utf-8")
    )
    return EvaluationBundle(corpus=corpus, dataset=dataset)
