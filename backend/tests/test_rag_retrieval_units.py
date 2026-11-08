import asyncio
from hashlib import sha256

import pytest

from app.services.document_ingestion import DocumentIngestionService
from evaluation.evidence_mapping import StoredChunk, align_chunks, map_evidence
from evaluation.pdf_fixture import render_pdf, verify_pdf
from evaluation.retrieval_metrics import score_at_k
from evaluation.schemas import DATA_DIRECTORY, load_document_dataset

CORPUS = load_document_dataset().corpus


@pytest.mark.parametrize("document", CORPUS.documents, ids=lambda doc: doc.key)
def test_corpus_pdf_round_trip(document, tmp_path):
    source = (DATA_DIRECTORY / "corpus" / document.path).read_text(encoding="utf-8")
    path = tmp_path / "fixture.pdf"
    path.write_bytes(render_pdf(source))
    assert path.read_bytes() == render_pdf(source)
    asyncio.run(
        verify_pdf(DocumentIngestionService(), path, source, [p.text for p in document.evidence])
    )


@pytest.mark.parametrize("change", ["EUR 350.00.", "EUR 300.00!"])
def test_pdf_verification_rejects_changed_financial_text(change, tmp_path):
    path = tmp_path / "changed.pdf"
    path.write_bytes(render_pdf(f"Planned expenses: {change}"))
    with pytest.raises(ValueError, match="changed fixture text"):
        asyncio.run(
            verify_pdf(DocumentIngestionService(), path, "Planned expenses: EUR 300.00.", [])
        )


def test_actual_chunker_aligns_long_document_and_split_passage(tmp_path):
    tokens = [f"word{i}" for i in range(700)]
    tokens[505:520] = [
        "only",
        "actual",
        "expenses",
        "were",
        "not",
        "confirmed",
        "as",
        "EUR",
        "300.00;",
        "draft",
        "budget",
        "remains",
        "under",
        "formal",
        "review.",
    ]
    source = " ".join(tokens)
    path = tmp_path / "long.pdf"
    path.write_bytes(render_pdf(source))
    service = DocumentIngestionService()
    anchor = " ".join(tokens[430:530])
    extracted = asyncio.run(verify_pdf(service, path, source, [anchor]))
    chunks = [
        StoredChunk(chunk.index, chunk.text, sha256(chunk.text.encode()).hexdigest())
        for chunk in service.chunk_text(extracted)
    ]
    spans = align_chunks(extracted, chunks, chunk_size=512, overlap=64)
    evidence = {("long", "split"): map_evidence(extracted, {"split": anchor})["split"]}
    assert spans == {0: (0, 512), 1: (448, 700)}
    assert score_at_k([("long", spans[0])], evidence, 1)["evidence_coverage"] == 0.82
    assert score_at_k([("long", spans[1]), ("long", spans[0])], evidence, 2)["evidence_recall"] == 1


@pytest.mark.parametrize("anchor", ["repeated", "missing", "EUR 4.00", "EUR 3.00!"])
def test_missing_or_ambiguous_anchor_is_rejected(anchor):
    with pytest.raises(ValueError, match="Missing or ambiguous"):
        map_evidence("repeated EUR 3.00. repeated", {"evidence": anchor})


def test_chunk_positions_resolve_duplicate_text_but_reject_duplicate_positions():
    text = "same same same"
    row = StoredChunk(0, "same same", sha256(b"same same").hexdigest())
    assert align_chunks(
        text, [row, StoredChunk(1, row.text, row.digest)], chunk_size=2, overlap=1
    ) == {0: (0, 2), 1: (1, 3)}
    with pytest.raises(ValueError, match="duplicate"):
        align_chunks(text, [row, row], chunk_size=2, overlap=1)


@pytest.mark.parametrize(
    ("chunk", "message"),
    [
        (StoredChunk(0, "EUR 3.00.", "bad"), "hash mismatch"),
        (StoredChunk(0, "EUR 4.00.", sha256(b"EUR 4.00.").hexdigest()), "Cannot align"),
    ],
)
def test_altered_persisted_chunks_are_rejected(chunk, message):
    with pytest.raises(ValueError, match=message):
        align_chunks("EUR 3.00.", [chunk], chunk_size=2, overlap=0)


def test_manual_metric_example():
    evidence = {("a", "first"): (1, 5), ("b", "second"): (0, 2)}
    ranking = [("other", (0, 20)), ("a", (1, 3)), ("a", (2, 5)), ("b", (0, 2)), ("b", (0, 2))]
    assert score_at_k(ranking, evidence, 2) == {
        "evidence_recall": 0,
        "evidence_coverage": 0.25,
        "chunk_precision": 0.5,
        "novel_evidence_precision": 0,
        "mrr": 0.5,
    }
    assert score_at_k(ranking, evidence, 6) == {
        "evidence_recall": 1,
        "evidence_coverage": 1,
        "chunk_precision": 4 / 6,
        "novel_evidence_precision": 1 / 6,
        "mrr": 0.5,
    }
    assert set(score_at_k([], evidence, 5).values()) == {0}
    assert set(score_at_k(ranking, {}, 5).values()) == {None}


def test_q14_complete_account_evidence_is_sufficient():
    bundle = load_document_dataset()
    case = next(case for case in bundle.dataset.cases if case.id == "Q14")
    spans = {}
    for document in bundle.corpus.documents:
        source = (DATA_DIRECTORY / "corpus" / document.path).read_text(encoding="utf-8")
        spans.update(
            ((document.key, key), span)
            for key, span in map_evidence(
                source, {anchor.key: anchor.text for anchor in document.evidence}
            ).items()
        )
    account = next(doc for doc in bundle.corpus.documents if doc.key == "account-january")
    source = (DATA_DIRECTORY / "corpus" / account.path).read_text(encoding="utf-8")
    gold = {
        (ref.document_key, ref.evidence_key): spans[ref.document_key, ref.evidence_key]
        for ref in case.relevant_evidence
    }

    scores = score_at_k([(account.key, (0, len(source.split())))], gold, 5)

    assert scores["evidence_recall"] == scores["evidence_coverage"] == 1.0
    assert set(gold) == {(account.key, key) for key in ("opening", "movements", "closing")}
    assert case.expected_sources == [account.key]
    assert set(case.document_scope) == {account.key, "revenue-january", "expenses-january"}
    assert case.category == "distractor"
