"""Integrity checks only, without retrieval or semantic grading."""

import copy
import hashlib
import json
import shutil

import pytest
from pydantic import ValidationError

from evaluation.schemas import DATA_DIRECTORY, EvaluationBundle, load_document_dataset


@pytest.fixture
def data():
    return load_document_dataset().model_dump()


def test_valid_dataset_and_corpus():
    bundle = load_document_dataset()
    assert len(bundle.corpus.documents) == 6
    assert sum(len(doc.evidence) for doc in bundle.corpus.documents) == 12
    assert len(bundle.dataset.cases) == 14
    assert {case.answerability for case in bundle.dataset.cases} == {
        "answerable",
        "insufficient_evidence",
        "ambiguous",
        "conflicting",
        "unauthorized",
    }


@pytest.mark.parametrize(
    ("target", "field", "value"),
    [
        ("case", "question", ""),
        ("case", "question", "  \n\t "),
        ("case", "question", "x" * 4001),
        ("case", "question", 123),
        ("case", "expected_outcome", "abstention_required"),
        ("case", "expected_http_status", 404),
        ("case", "expected_sources", ["missing"]),
        ("case", "expected_sources", ["account-january", "account-january"]),
        ("case", "document_scope", ["missing"]),
        ("case", "document_scope", []),
        ("case", "document_scope", ["account-january", "account-january"]),
        ("case", "document_scope", ["private-plan"]),
        ("case", "relevant_evidence", [{"document_key": "missing", "evidence_key": "closing"}]),
        (
            "case",
            "relevant_evidence",
            [{"document_key": "account-january", "evidence_key": "missing"}],
        ),
        (
            "case",
            "relevant_evidence",
            [{"document_key": "expenses-january", "evidence_key": "breakdown"}],
        ),
        ("case", "required_assertions", [{"text": "", "rationale": "review", "evidence": []}]),
        ("case", "required_assertions", [{"text": "claim", "evidence": []}]),
        ("case", "required_assertions", [{"text": "claim", "rationale": "review", "evidence": []}]),
        ("case", "required_assertions", ["unstructured"]),
        ("case", "unexpected_field", "typo"),
        ("document", "revision_sha256", "not-a-hash"),
        ("document", "revision_sha256", "A" * 64),
        ("document", "owner", ""),
        ("dataset", "corpus_version", "9.0.0"),
    ],
)
def test_invalid_annotations(data, target, field, value):
    targets = {
        "case": data["dataset"]["cases"][0],
        "document": data["corpus"]["documents"][0],
        "dataset": data["dataset"],
    }
    targets[target][field] = value
    with pytest.raises(ValidationError):
        EvaluationBundle.model_validate(data)


@pytest.mark.parametrize("kind", ["case", "document", "evidence", "relevance"])
def test_duplicates(data, kind):
    rows = {
        "case": data["dataset"]["cases"],
        "document": data["corpus"]["documents"],
        "evidence": data["corpus"]["documents"][0]["evidence"],
        "relevance": data["dataset"]["cases"][0]["relevant_evidence"],
    }[kind]
    rows.append(copy.deepcopy(rows[0]))
    with pytest.raises(ValidationError):
        EvaluationBundle.model_validate(data)


def test_contradictory_assertions(data):
    case = data["dataset"]["cases"][0]
    case["forbidden_assertions"] = copy.deepcopy(case["required_assertions"])
    with pytest.raises(ValidationError, match="Contradictory assertions"):
        EvaluationBundle.model_validate(data)


def test_authorization_negative_requires_foreign_scope(data):
    data["dataset"]["cases"][9]["document_scope"] = ["account-january"]
    with pytest.raises(ValidationError, match="ownership"):
        EvaluationBundle.model_validate(data)


def test_authorization_evidence_does_not_allow_returning_foreign_sources(data):
    case = data["dataset"]["cases"][9]
    case["relevant_evidence"] = [{"document_key": "private-plan", "evidence_key": "private"}]
    assert EvaluationBundle.model_validate(data).dataset.cases[9].expected_sources == []
    case["expected_sources"] = ["private-plan"]
    with pytest.raises(ValidationError):
        EvaluationBundle.model_validate(data)


def test_authorization_exception_still_checks_references(data):
    data["dataset"]["cases"][9]["relevant_evidence"] = [
        {"document_key": "private-plan", "evidence_key": "missing"}
    ]
    with pytest.raises(ValidationError, match="Unknown evidence"):
        EvaluationBundle.model_validate(data)


@pytest.mark.parametrize("answerability", ["insufficient_evidence", "ambiguous", "conflicting"])
def test_nonanswer_cannot_expect_ok(data, answerability):
    data["dataset"]["cases"][0]["answerability"] = answerability
    with pytest.raises(ValidationError, match="Contradictory expected status"):
        EvaluationBundle.model_validate(data)


@pytest.fixture
def copied_data(tmp_path):
    destination = tmp_path / "data"
    shutil.copytree(DATA_DIRECTORY / "corpus", destination / "corpus")
    shutil.copyfile(DATA_DIRECTORY / "document_qa_v1.json", destination / "document_qa_v1.json")
    return destination


def test_hash_mismatch(copied_data):
    (copied_data / "corpus" / "account-january.txt").write_bytes(b"changed")
    with pytest.raises(ValueError, match="Content hash mismatch"):
        load_document_dataset(copied_data)


@pytest.mark.parametrize("replacement", ["absent evidence", "SYNTHETIC"])
def test_passage_anchor(copied_data, replacement):
    path = copied_data / "corpus" / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["documents"][0]["evidence"][0]["text"] = replacement
    if replacement == "SYNTHETIC":
        document = copied_data / "corpus" / "account-january.txt"
        payload = document.read_bytes() + b"SYNTHETIC\n"
        document.write_bytes(payload)
        manifest["documents"][0]["revision_sha256"] = hashlib.sha256(payload).hexdigest()
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="one exact passage"):
        load_document_dataset(copied_data)


@pytest.mark.parametrize("relative", ["../outside.txt", "account-january.pdf"])
def test_unsafe_paths(copied_data, relative):
    path = copied_data / "corpus" / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["documents"][0]["path"] = relative
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="inside corpus"):
        load_document_dataset(copied_data)


def test_document_paths_are_unique(data):
    data["corpus"]["documents"][1]["path"] = data["corpus"]["documents"][0]["path"]
    with pytest.raises(ValidationError, match="Duplicate document paths"):
        EvaluationBundle.model_validate(data)


def test_assertion_references_must_be_relevant(data):
    case = data["dataset"]["cases"][0]
    case["required_assertions"][0]["evidence"] = [
        {"document_key": "account-january", "evidence_key": "opening"}
    ]
    with pytest.raises(ValidationError, match="Required assertion lacks relevant evidence"):
        EvaluationBundle.model_validate(data)


def test_legacy_report_matches_versioned_baseline(monkeypatch):
    # Import after explicitly isolating configuration; no production DB/provider access.
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("JWT_SECRET_KEY", "pr1-test-access-placeholder-1234567890")
    monkeypatch.setenv("JWT_REFRESH_SECRET_KEY", "pr1-test-refresh-placeholder-1234567890")
    monkeypatch.setenv("OPENAI_API_KEY", "pr1-test-placeholder-no-real-provider")
    from evaluation.runner import evaluate

    baseline = json.loads((DATA_DIRECTORY.parent / "baseline.json").read_text())
    assert evaluate() == baseline


def test_synthetic_financial_facts_reconcile():
    from decimal import Decimal

    corpus = load_document_dataset().corpus
    passages = {
        (doc.key, passage.key): passage.text for doc in corpus.documents for passage in doc.evidence
    }
    # Extract only explicitly annotated money values from the fixed corpus.
    # These checks validate fixture arithmetic, never score an application answer.
    import re

    def amounts(document, evidence):
        return [
            Decimal(value)
            for value in re.findall(r"EUR ([0-9]+\.[0-9]{2})", passages[(document, evidence)])
        ]

    (opening,) = amounts("account-january", "opening")
    receipts, payments = amounts("account-january", "movements")
    (closing,) = amounts("account-january", "closing")
    supplies, utilities, expenses = amounts("expenses-january", "breakdown")
    revenue, unpaid = amounts("revenue-january", "recognized")
    (collected,) = amounts("revenue-january", "cash")
    assert opening + receipts - payments == closing
    assert supplies + utilities == expenses == payments
    assert revenue - unpaid == collected == receipts


def test_unauthorized_case_rejects_evidence_outside_requested_scope(data):
    # Q10 requests only private-plan, but this known passage belongs to account-january.
    data["dataset"]["cases"][9]["relevant_evidence"] = [
        {"document_key": "account-january", "evidence_key": "closing"}
    ]
    with pytest.raises(ValidationError, match="Evidence outside document scope"):
        EvaluationBundle.model_validate(data)


def test_semantic_outcome_and_literal_status_are_separate():
    cases = {case.id: case for case in load_document_dataset().dataset.cases}
    assert cases["Q01"].expected_outcome == "answerable"
    assert cases["Q01"].expected_api_status == "ok"
    assert cases["Q06"].expected_outcome == "abstention_required"
    assert cases["Q06"].expected_api_status is None
    for key in ("Q10", "Q11"):
        assert cases[key].expected_outcome == "authorization_denied"
        assert cases[key].expected_api_status is None
        assert cases[key].expected_http_status == 404


def test_q06_forbids_plan_and_draft_as_confirmed_actuals():
    case = next(case for case in load_document_dataset().dataset.cases if case.id == "Q06")
    assert case.answerability == "insufficient_evidence"
    assert {assertion.text for assertion in case.forbidden_assertions} >= {
        "Actual February expenses were EUR 300.00.",
        "Actual February expenses were EUR 350.00.",
    }


@pytest.mark.parametrize(
    ("case_index", "api_status"),
    [
        (0, None),
        (0, "abstained"),
        (5, "ok"),
        (9, "insufficient_evidence"),
        (9, "authorization_denied"),
        (5, "provider_error"),
    ],
)
def test_contradictory_literal_api_status_rejected(data, case_index, api_status):
    data["dataset"]["cases"][case_index]["expected_api_status"] = api_status
    with pytest.raises(ValidationError):
        EvaluationBundle.model_validate(data)


@pytest.mark.parametrize("api_status", [None, "abstained", "insufficient_evidence"])
def test_abstention_can_have_nullable_or_explicit_api_status(data, api_status):
    data["dataset"]["cases"][5]["expected_api_status"] = api_status
    assert EvaluationBundle.model_validate(data).dataset.cases[5].expected_api_status == api_status


def test_retired_expected_status_field_is_rejected(data):
    data["dataset"]["cases"][0]["expected_status"] = "ok"
    with pytest.raises(ValidationError):
        EvaluationBundle.model_validate(data)
