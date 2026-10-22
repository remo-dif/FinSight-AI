"""Async document ingestion, chunking, embedding, and vector persistence."""

import asyncio
import csv
import hashlib
import io
import logging
import re
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import ClassVar
from uuid import UUID, uuid4

import pdfplumber
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException, UploadFile, status
from openai import OpenAIError
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.openai_resilience import (
    CircuitOpenError,
    create_async_openai_client,
    openai_circuit,
    validate_embedding_response,
)
from app.models.case import InvestigationCase
from app.models.embedding import EMBEDDING_DIMENSIONS, Embedding
from app.models.finance import Transaction, UploadedFile
from app.schemas.finance import TransactionCreate
from app.services.audit import AsyncAuditService
from app.services.categorization import CategorizationService
from app.services.rag import LOCAL_EMBEDDING_MODEL, RagService

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"\S+")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_PDF_PAGES = 25
MAX_IMAGE_PIXELS = 20_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


@dataclass(frozen=True)
class StoredUpload:
    path: Path
    storage_uri: str
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


@dataclass(frozen=True)
class PreparedIngestion:
    transactions: tuple[TransactionCreate, ...] = ()
    chunks: tuple[DocumentChunk, ...] = ()
    vectors: tuple[tuple[float, ...], ...] = ()
    status: str = "indexed"


class DocumentIngestionService:
    allowed_content_types: ClassVar[dict[str, set[str]]] = {
        "text/csv": {".csv"},
        "application/pdf": {".pdf"},
        "image/png": {".png"},
        "image/jpeg": {".jpg", ".jpeg"},
    }
    magic_bytes: ClassVar[dict[str, tuple[bytes, ...]]] = {
        ".pdf": (b"%PDF-",),
        ".png": (b"\x89PNG\r\n\x1a\n",),
        ".jpg": (b"\xff\xd8\xff",),
        ".jpeg": (b"\xff\xd8\xff",),
    }

    def __init__(self, categorizer: CategorizationService | None = None) -> None:
        self.categorizer = categorizer or CategorizationService()
        self._embedding_backend = settings.embedding_backend
        self._embedding_model = (
            LOCAL_EMBEDDING_MODEL
            if self._embedding_backend == "local"
            else settings.openai_embedding_model
        )
        self._openai_client = (
            None if self._embedding_backend == "local" else create_async_openai_client()
        )
        self._owned_staging: set[Path] = set()
        self._owned_objects: dict[str, dict] = {}

    async def save_upload(
        self, user_id: UUID, file: UploadFile, *, stage_only: bool = False
    ) -> StoredUpload:
        filename = file.filename or "upload"
        suffix = Path(filename).suffix.lower()
        content_type = file.content_type or "application/octet-stream"
        self._validate_metadata(suffix, content_type)

        user_dir = settings.upload_dir / "staging" / str(user_id)
        await asyncio.to_thread(user_dir.mkdir, parents=True, exist_ok=True)
        path = user_dir / f"{uuid4()}{suffix}"
        max_bytes = settings.max_upload_mb * 1024 * 1024
        total_bytes = 0
        first_bytes = b""

        try:
            # Exclusive creation is the ownership boundary. A collision is never ours to clean up.
            await asyncio.to_thread(self._create_staging, path)
            self._owned_staging.add(path)
            while chunk := await file.read(1024 * 1024):
                if not first_bytes:
                    first_bytes = chunk[:16]
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise HTTPException(
                        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is too large"
                    )
                await asyncio.to_thread(self._append_bytes, path, chunk)
        except BaseException:
            await self._cleanup_stage(path)
            raise

        if total_bytes == 0:
            await self._cleanup_stage(path)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is empty")
        try:
            self._validate_magic_bytes(suffix, first_bytes)
        except BaseException:
            await self._cleanup_stage(path)
            raise
        upload = StoredUpload(
            path=path,
            storage_uri=str(path),
            filename=filename,
            content_type=content_type,
            suffix=suffix,
            size_bytes=total_bytes,
        )
        if not stage_only:
            try:
                upload = await self.finalize_storage(user_id, upload)
            except BaseException:
                await self._cleanup_stage(path)
                raise
        return upload

    @staticmethod
    def _create_staging(path: Path) -> None:
        with path.open("xb"):
            pass

    async def _cleanup_stage(self, path: Path) -> None:
        if path not in self._owned_staging:
            return
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except OSError:
            logger.warning(
                "Upload staging cleanup incomplete", extra={"event": "upload.cleanup_incomplete"}
            )
        else:
            self._owned_staging.discard(path)

    async def finalize_storage(self, user_id: UUID, upload: StoredUpload) -> StoredUpload:
        if settings.storage_backend != "s3":
            return upload
        if upload.path not in self._owned_staging:
            raise ValueError("Cannot publish a staging file not owned by this request")
        key = f"{settings.s3_upload_prefix.strip('/')}/{user_id}/{upload.path.name}"
        uri = f"s3://{settings.s3_upload_bucket}/{key}"
        # Conditional creation prevents overwriting even if a UUID/key collision occurs.
        receipt = await asyncio.to_thread(self._upload_to_s3, upload.path, key, upload.content_type)
        if receipt and receipt.get("ETag"):
            self._owned_objects[uri] = {
                "Bucket": settings.s3_upload_bucket,
                "Key": key,
                "IfMatch": receipt["ETag"],
            }
            if receipt.get("VersionId"):
                self._owned_objects[uri]["VersionId"] = receipt["VersionId"]
        return replace(upload, storage_uri=uri)

    async def cleanup_upload(self, upload: StoredUpload) -> None:
        receipt = self._owned_objects.pop(upload.storage_uri, None)
        if receipt:
            try:
                await asyncio.to_thread(self._delete_owned_s3, receipt)
            except (OSError, BotoCoreError, ClientError):
                logger.warning(
                    "Upload storage cleanup incomplete",
                    extra={"event": "upload.cleanup_incomplete"},
                )
        await self._cleanup_stage(upload.path)

    async def release_upload(self, upload: StoredUpload) -> None:
        """Keep final storage after success or an ambiguous commit outcome."""
        self._owned_objects.pop(upload.storage_uri, None)
        if upload.storage_uri.startswith("s3://"):
            await self._cleanup_stage(upload.path)
        else:
            self._owned_staging.discard(upload.path)

    @staticmethod
    def _delete_owned_s3(receipt: dict) -> None:
        import boto3

        boto3.client("s3").delete_object(**receipt)

    async def prepare_upload(self, upload: StoredUpload) -> PreparedIngestion:
        if upload.suffix == ".csv":
            payload = await asyncio.to_thread(upload.path.read_bytes)
            transactions = await asyncio.to_thread(self.parse_csv, payload)
            return PreparedIngestion(transactions=tuple(transactions), status="processed")
        text = await self.extract_document_text(upload.path)
        chunks = tuple(self.chunk_text(text))
        if not chunks:
            raise HTTPException(
                400,
                "No indexable text was found. Upload a text-based PDF or CSV; scanned documents may require OCR.",
            )
        vectors = await self.embed_texts([chunk.text for chunk in chunks])
        return PreparedIngestion(chunks=chunks, vectors=tuple(tuple(v) for v in vectors))

    async def ingest_upload(
        self,
        db: AsyncSession,
        user_id: UUID,
        upload: StoredUpload,
        record: UploadedFile,
        prepared: PreparedIngestion | None = None,
    ) -> IngestionResult:
        if prepared is None:
            if hasattr(db, "in_transaction") and db.in_transaction():
                raise RuntimeError("Prepare the upload before opening a persistence transaction")
            prepared = await self.prepare_upload(upload)
        audit = AsyncAuditService(db)
        await audit.record(
            "document_ingestion.started",
            user_id,
            {
                "file_id": str(record.id),
                "content_type": upload.content_type,
                "size_bytes": upload.size_bytes,
            },
        )

        if prepared.status == "processed":
            rows = [
                Transaction(user_id=user_id, **item.model_dump()) for item in prepared.transactions
            ]
            db.add_all(rows)
            await db.flush()
            db.add_all([InvestigationCase(transaction_id=row.id) for row in rows])
            await db.flush()
            await audit.record(
                "document_ingestion.csv_processed",
                user_id,
                {"file_id": str(record.id), "rows": len(rows)},
            )
            return IngestionResult(status="processed", imported=len(rows))

        records = self._embedding_records(
            user_id, "upload", record.id, prepared.chunks, prepared.vectors
        )
        db.add_all(records)
        await db.flush()
        indexed = len(records)
        await audit.record(
            "document_ingestion.document_indexed",
            user_id,
            {"file_id": str(record.id), "chunks": indexed},
        )
        return IngestionResult(status=prepared.status, indexed=indexed)

    async def index_text(
        self,
        db: AsyncSession,
        user_id: UUID,
        source_type: str,
        source_id: UUID | None,
        text: str,
    ) -> int:
        if hasattr(db, "in_transaction") and db.in_transaction():
            raise RuntimeError("Generate embeddings before opening a persistence transaction")
        chunks = self.chunk_text(text)
        if not chunks:
            return 0

        embeddings = await self.embed_texts([chunk.text for chunk in chunks])
        records = self._embedding_records(user_id, source_type, source_id, chunks, embeddings)
        db.add_all(records)
        await db.flush()
        return len(records)

    def _embedding_records(self, user_id, source_type, source_id, chunks, embeddings):
        return [
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

    def chunk_text(
        self, text: str, chunk_tokens: int = 512, overlap_tokens: int = 64
    ) -> list[DocumentChunk]:
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
        if self._embedding_backend == "local":
            return [self._local_embedding(value) for value in values]
        if self._openai_client is None:
            raise HTTPException(
                503,
                "Remote embedding provider is not configured. Configure credentials or explicitly select EMBEDDING_BACKEND=local; retry the upload afterward.",
            )
        try:
            openai_circuit.before_call()
            response = await self._openai_client.embeddings.create(
                model=settings.openai_embedding_model,
                input=values,
                dimensions=EMBEDDING_DIMENSIONS,
            )
        except CircuitOpenError as exc:
            raise HTTPException(
                503,
                "Embedding provider is cooling down. Retry the upload later; no model was substituted.",
            ) from exc
        except OpenAIError as exc:
            openai_circuit.record_failure()
            raise HTTPException(
                503,
                "Embedding provider unavailable. Retry the upload later; no embedding model was substituted.",
            ) from exc
        try:
            vectors = validate_embedding_response(
                response, self.embedding_model, len(values), EMBEDDING_DIMENSIONS
            )
        except (AttributeError, TypeError, ValueError, OverflowError) as exc:
            openai_circuit.record_failure()
            raise HTTPException(
                503, "Invalid embedding provider response. Retry the upload; nothing was indexed."
            ) from exc
        openai_circuit.record_success()
        return vectors

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
                raise HTTPException(
                    status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "CSV has too many rows"
                )
            merchant = (
                raw.get("merchant") or raw.get("Merchant") or raw.get("description") or "Unknown"
            )
            description = raw.get("description") or raw.get("Description") or merchant
            try:
                amount = Decimal(str(raw.get("amount") or raw.get("Amount") or "0"))
                if not amount.is_finite():
                    raise ValueError("Non-finite monetary value")
                posted_at = datetime.fromisoformat(raw.get("date") or raw.get("Date")).date()
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Invalid CSV transaction data on line {line_number}",
                ) from exc
            category = raw.get("category") or self.categorizer.categorize(
                merchant, description, amount
            )
            try:
                item = TransactionCreate(
                    posted_at=posted_at,
                    merchant=merchant,
                    description=description,
                    amount=amount,
                    currency=raw.get("currency") or raw.get("Currency") or "USD",
                    category=category,
                    source="csv",
                )
            except ValidationError as exc:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"Invalid CSV transaction data on line {line_number}",
                ) from exc
            rows.append(item)
        return rows

    @property
    def embedding_model(self) -> str:
        return self._embedding_model

    def _validate_metadata(self, suffix: str, content_type: str) -> None:
        allowed_suffixes = self.allowed_content_types.get(content_type)
        if allowed_suffixes is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported content type")
        if suffix not in allowed_suffixes:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "File extension does not match content type"
            )

    def _validate_magic_bytes(self, suffix: str, first_bytes: bytes) -> None:
        expected = self.magic_bytes.get(suffix)
        if expected and not any(first_bytes.startswith(signature) for signature in expected):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "File content does not match extension"
            )

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
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "Image could not be parsed"
                ) from exc
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
        return RagService._local_embedding(value)

    @staticmethod
    def _append_bytes(path: Path, payload: bytes) -> None:
        with path.open("ab") as handle:
            handle.write(payload)

    @staticmethod
    def _upload_to_s3(path: Path, key: str, content_type: str) -> dict:
        import boto3

        extra_args = {"ContentType": content_type, "ServerSideEncryption": "AES256"}
        if settings.s3_kms_key_id:
            extra_args.update(
                ServerSideEncryption="aws:kms",
                SSEKMSKeyId=settings.s3_kms_key_id,
            )
        with path.open("rb") as body:
            return boto3.client("s3").put_object(
                Bucket=settings.s3_upload_bucket, Key=key, Body=body, IfNoneMatch="*", **extra_args
            )
