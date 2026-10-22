from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services.document_ingestion import DocumentIngestionService
from tests.test_cycle2_uploads import configure


@pytest.mark.parametrize("kind", ["characters", "chunks"])
def test_document_budget_rejects_before_embedding(monkeypatch, kind):
    configure(monkeypatch, document_max_extracted_chars=1_000_000, document_max_chunks=128)
    service = DocumentIngestionService()
    text = "a" * 1_000_001 if kind == "characters" else "word " * (448 * 129)
    with pytest.raises(HTTPException) as exc:
        service.chunk_text(text)
    assert exc.value.status_code == 413


@pytest.mark.asyncio
@pytest.mark.parametrize("values", [["x"] * 129, ["x" * 1_000_001]])
async def test_provider_boundary_enforces_budget(monkeypatch, values):
    configure(
        monkeypatch,
        embedding_backend="local",
        document_max_extracted_chars=1_000_000,
        document_max_chunks=128,
    )
    with pytest.raises(HTTPException) as exc:
        await DocumentIngestionService().embed_texts(values)
    assert exc.value.status_code == 413


def test_pdf_extraction_stops_before_reading_later_pages(monkeypatch):
    from pathlib import Path

    configure(monkeypatch, document_max_extracted_chars=10, document_max_chunks=128)
    calls = []

    def extract():
        calls.append(True)
        return "x" * 11

    class Pdf:
        def __init__(self):
            self.pages = [SimpleNamespace(extract_text=extract), SimpleNamespace(extract_text=extract)]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("app.services.document_ingestion.pdfplumber.open", lambda path: Pdf())
    with pytest.raises(HTTPException) as exc:
        DocumentIngestionService()._extract_document_text_sync(Path("synthetic.pdf"))
    assert exc.value.status_code == 413
    assert len(calls) == 1


def test_unbounded_document_configuration_is_rejected():
    from pydantic import ValidationError

    from app.core.config import Settings

    for values in [
        {"document_max_extracted_chars": 0},
        {"document_max_extracted_chars": 1_000_001},
        {"document_max_chunks": 0},
        {"document_max_chunks": 129},
    ]:
        with pytest.raises(ValidationError):
            Settings(**values)
