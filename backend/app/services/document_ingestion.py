"""Async document ingestion, chunking, embedding, and vector persistence."""

import asyncio
import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID, uuid4

import pdfplumber
from fastapi import HTTPException, UploadFile, status
from openai import AsyncOpenAI
from PIL import Image, UnidentifiedImageError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.embedding import EMBEDDING_DIMENSIONS, Embedding
from app.models.finance import Transaction, UploadedFile
from app.schemas.finance import TransactionCreate
from app.services.audit import AsyncAuditService
from app.services.categorization import CategorizationService
from app.services.rag import LOCAL_EMBEDDING_MODEL


_TOKEN_RE = re.compile(r"\S+")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_PDF_PAGES = 25
MAX_IMAGE_PIXELS = 20_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


@dataclass(frozen=True)
class StoredUpload:
    path: Path
    filename: str
    content_type: str
    suffix: str
    size_bytes: int


@dataclass(frozen=True)
class DocumentChunk:
    index: int
    text: str
    token_count: int


@dataclass(frozen=True)
class IngestionResult:
    status: str
    imported: int = 0
    indexed: int = 0


class DocumentIngestionService:
    allowed_content_types: dict[str, set[str]] = {
        "text/csv": {".csv"},
        "application/pdf": {".pdf"},
        "image/png": {".png"},
        "image/jpeg": {".jpg", ".jpeg"},
    }
    magic_bytes: dict[str, tuple[bytes, ...]] = {
        ".pdf": (b"%PDF-",),
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".jpg": (b"\xff\xd8\xff",),
        ".jpeg": (b"\xff\xd8\xff",),
    }

    def __init__(self, categorizer: CategorizationService | None = None) -> None:
        self.categorizer = categorizer or CategorizationService()
        self._openai_client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    async def save_upload(self, user_id: UUID, file: UploadFile) -> StoredUpload:
        filename = file.filename or "upload"
        suffix = Path(filename).suffix.lower()
        content_type = file.content_type or "application/octet-stream"
        self._validate_metadata(suffix, content_type)

        user_dir = settings.upload_dir / str(user_id)
        await asyncio.to_thread(user_dir.mkdir, parents=True, exist_ok=True)
        path = user_dir / f"{uuid4()}{suffix}"
        max_bytes = settings.max_upload_mb * 1024 * 1024
        total_bytes = 0
        first_bytes = b""

        try:
            while chunk := await file.read(1024 * 1024):
                if not first_bytes:
                    first_bytes = chunk[:16]
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is too large")
                await asyncio.to_thread(self._append_bytes, path, chunk)
        except Exception:
            await asyncio.to_thread(path.unlink, missing_ok=True)
            raise

        if total_bytes == 0:
            await asyncio.to_thread(path.unlink, missing_ok=True)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is empty")
        self._validate_magic_bytes(suffix, first_bytes)
        return StoredUpload(
            path=path,
            filename=filename,
            content_type=content_type,
            suffix=suffix,
            size_bytes=total_bytes,
        )

    async def ingest_upload(
        self,
        db: AsyncSession,
        user_id: UUID,
        upload: StoredUpload,
        record: UploadedFile,
    ) -> IngestionResult:
        audit = AsyncAuditService(db)
        await audit.record(
            "document_ingestion.started",
            user_id,
            {"file_id": str(record.id), "content_type": upload.content_type, "size_bytes": upload.size_bytes},
        )

        if upload.suffix == ".csv":
            payload = await asyncio.to_thread(upload.path.read_bytes)
            transactions = await asyncio.to_thread(self.parse_csv, payload)
            rows = [Transaction(user_id=user_id, **item.model_dump()) for item in transactions]
            db.add_all(rows)
            await db.flush()
            await audit.record(
                "document_ingestion.csv_processed",
                user_id,
                {"file_id": str(record.id), "rows": len(rows)},
            )
            return IngestionResult(status="processed", imported=len(rows))

        text = await self.extract_document_text(upload.path)
        indexed = await self.index_text(db, user_id, "upload", record.id, text)
        await audit.record(
            "document_ingestion.document_indexed",
            user_id,
            {"file_id": str(record.id), "chunks": indexed},
        )
        return IngestionResult(status="indexed", indexed=indexed)

    async def index_text(
        self,
        db: AsyncSession,
        user_id: UUID,
        source_type: str,
        source_id: UUID | None,
        text: str,
    ) -> int:
        chunks = self.chunk_text(text)
        if not chunks:
            return 0

        embeddings = await self.embed_texts([chunk.text for chunk in chunks])
        records = [
            Embedding(
                user_id=user_id,
                source_type=source_type,
                source_id=source_id,
                chunk_index=chunk.index,
                chunk_text=chunk.text,
                chunk_hash=hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
                embedding=embedding,
                embedding_model=self.embedding_model,
                embedding_dimensions=len(embedding),
                metadata_json={
                    "source": {"type": source_type, "id": str(source_id) if source_id else None},
                    "chunk": {"index": chunk.index, "token_count": chunk.token_count},
                },
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ]
        db.add_all(records)
        await db.flush()
        return len(records)

    def chunk_text(self, text: str, chunk_tokens: int = 512, overlap_tokens: int = 64) -> list[DocumentChunk]:
        if chunk_tokens <= 0:
            raise ValueError("chunk_tokens must be positive")
        if overlap_tokens < 0 or overlap_tokens >= chunk_tokens:
            raise ValueError("overlap_tokens must be between 0 and chunk_tokens - 1")

        normalized = self._normalize_text(text)
        tokens = _TOKEN_RE.findall(normalized)
        if not tokens:
            return []

        chunks: list[DocumentChunk] = []
        start = 0
        while start < len(tokens):
            end = min(start + chunk_tokens, len(tokens))
            chunk = " ".join(tokens[start:end])
            chunks.append(DocumentChunk(index=len(chunks), text=chunk, token_count=end - start))
            if end >= len(tokens):
                break
            start = end - overlap_tokens
        return chunks

    async def embed_texts(self, values: list[str]) -> list[list[float]]:
        if not values:
            return []
        if self._openai_client is None:
            return [self._local_embedding(value) for value in values]

        response = await self._openai_client.embeddings.create(
            model=settings.openai_embedding_model,
            input=values,
            dimensions=EMBEDDING_DIMENSIONS,
        )
        return [[float(item) for item in row.embedding] for row in response.data]

    async def extract_document_text(self, path: Path) -> str:
        return await asyncio.to_thread(self._extract_document_text_sync, path)

    def parse_csv(self, payload: bytes) -> list[TransactionCreate]:
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "CSV must be UTF-8 encoded") from exc

        reader = csv.DictReader(io.StringIO(text))
        rows: list[TransactionCreate] = []
        for line_number, raw in enumerate(reader, start=2):
            if len(rows) >= 5000:
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "CSV has too many rows")
            merchant = raw.get("merchant") or raw.get("Merchant") or raw.get("description") or "Unknown"
            description = raw.get("description") or raw.get("Description") or merchant
            try:
                amount = Decimal(str(raw.get("amount") or raw.get("Amount") or "0"))
                posted_at = datetime.fromisoformat(raw.get("date") or raw.get("Date")).date()
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Invalid CSV transaction data on line {line_number}",
                ) from exc
            category = raw.get("category") or self.categorizer.categorize(merchant, description, amount)
            rows.append(
                TransactionCreate(
                    posted_at=posted_at,
                    merchant=merchant,
                    description=description,
                    amount=amount,
                    category=category,
                    source="csv",
                )
            )
        return rows

    @property
    def embedding_model(self) -> str:
        if self._openai_client is None:
            return LOCAL_EMBEDDING_MODEL
        return settings.openai_embedding_model

    def _validate_metadata(self, suffix: str, content_type: str) -> None:
        allowed_suffixes = self.allowed_content_types.get(content_type)
        if allowed_suffixes is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported content type")
        if suffix not in allowed_suffixes:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "File extension does not match content type")

    def _validate_magic_bytes(self, suffix: str, first_bytes: bytes) -> None:
        expected = self.magic_bytes.get(suffix)
        if expected and not any(first_bytes.startswith(signature) for signature in expected):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "File content does not match extension")

    def _extract_document_text_sync(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            try:
                pdf = pdfplumber.open(path)
            except Exception as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "PDF could not be parsed") from exc
            with pdf:
                if len(pdf.pages) > MAX_PDF_PAGES:
                    raise HTTPException(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        f"PDF has too many pages; maximum is {MAX_PDF_PAGES}",
                    )
                return "\n".join(page.extract_text() or "" for page in pdf.pages)
        if suffix in {".png", ".jpg", ".jpeg"}:
            try:
                with Image.open(path) as image:
                    width, height = image.size
                    image.verify()
            except (UnidentifiedImageError, OSError) as exc:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "Image could not be parsed") from exc
            if width * height > MAX_IMAGE_PIXELS:
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    f"Image has too many pixels; maximum is {MAX_IMAGE_PIXELS}",
                )
            return f"Image uploaded: {width}x{height}. OCR runtime available via pytesseract."
        return ""

    def _normalize_text(self, value: str) -> str:
        normalized = value.replace("\r\n", "\n").replace("\r", "\n")
        normalized = _CONTROL_CHARS.sub(" ", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    def _local_embedding(self, value: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIMENSIONS
        tokens = [token.lower() for token in _TOKEN_RE.findall(value)]
        if not tokens:
            tokens = [hashlib.sha256(value.encode("utf-8")).hexdigest()]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
            vector[index] += 1.0 if digest[4] & 1 else -1.0
        norm = sum(item * item for item in vector) ** 0.5
        if norm == 0:
            return vector
        return [item / norm for item in vector]

    @staticmethod
    def _append_bytes(path: Path, payload: bytes) -> None:
        with path.open("ab") as handle:
            handle.write(payload)
