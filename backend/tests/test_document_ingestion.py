"""Async tests for the document ingestion service."""

from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from app.models.finance import UploadedFile
from app.services.document_ingestion import DocumentIngestionService, StoredUpload
from app.services.rag import LOCAL_EMBEDDING_MODEL


class FakeAsyncSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = 0

    def add(self, item: object) -> None:
        self.added.append(item)

    def add_all(self, items: list[object]) -> None:
        self.added.extend(items)

    async def flush(self) -> None:
        self.flushed += 1


def upload_file(filename: str, content_type: str, payload: bytes) -> UploadFile:
    return UploadFile(
        BytesIO(payload),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )


@pytest.mark.asyncio
async def test_save_upload_rejects_mismatched_extension_and_content_type():
    service = DocumentIngestionService()
    file = upload_file("statement.pdf", "text/csv", b"date,merchant,amount\n2026-05-01,Cafe,-4.25\n")

    with pytest.raises(HTTPException) as exc:
        await service.save_upload(uuid4(), file)

    assert exc.value.status_code == 400
    assert exc.value.detail == "File extension does not match content type"


@pytest.mark.asyncio
async def test_embed_texts_uses_local_embedding_without_api_key(monkeypatch):
    monkeypatch.setattr("app.services.document_ingestion.settings.openai_api_key", None)
    service = DocumentIngestionService()

    embeddings = await service.embed_texts(["rent payment", "grocery store"])

    assert service.embedding_model == LOCAL_EMBEDDING_MODEL
    assert len(embeddings) == 2
    assert len(embeddings[0]) == 1536


def test_chunk_text_uses_512_tokens_with_64_token_overlap():
    service = DocumentIngestionService()
    text = " ".join(f"token-{index}" for index in range(600))

    chunks = service.chunk_text(text)

    assert len(chunks) == 2
    assert chunks[0].token_count == 512
    assert chunks[1].text.startswith("token-448 ")


@pytest.mark.asyncio
async def test_ingest_upload_imports_csv_transactions_and_audits():
    service = DocumentIngestionService()
    user_id = uuid4()
    path = Path("pytest-document-ingestion.csv")
    path.write_bytes(b"date,merchant,amount,category\n2026-05-01,Cafe,-4.25,Dining\n")
    try:
        upload = StoredUpload(
            path=path,
            filename="transactions.csv",
            content_type="text/csv",
            suffix=".csv",
            size_bytes=path.stat().st_size,
        )
        record = UploadedFile(
            id=uuid4(),
            user_id=user_id,
            filename=upload.filename,
            content_type=upload.content_type,
            storage_path=str(path),
            status="stored",
        )
        db = FakeAsyncSession()

        result = await service.ingest_upload(db, user_id, upload, record)  # type: ignore[arg-type]

        assert result.status == "processed"
        assert result.imported == 1
        assert db.flushed == 1
        assert len(db.added) == 3
    finally:
        path.unlink(missing_ok=True)
