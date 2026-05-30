import csv
import io
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import UUID, uuid4

import pdfplumber
from fastapi import HTTPException, UploadFile, status
from PIL import Image

from app.core.config import settings
from app.schemas.finance import TransactionCreate
from app.services.categorization import CategorizationService


class SecureUploadService:
    allowed_content_types = {
        "text/csv": ".csv",
        "application/pdf": ".pdf",
        "image/png": ".png",
        "image/jpeg": ".jpg",
    }
    allowed_extensions = {".csv", ".pdf", ".png", ".jpg", ".jpeg"}

    def validate_metadata(self, file: UploadFile) -> None:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in self.allowed_extensions:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported file extension")
        if file.content_type not in self.allowed_content_types:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported content type")

    def validate_payload(self, payload: bytes, suffix: str) -> None:
        signatures = {
            ".pdf": b"%PDF-",
            ".png": b"\x89PNG\r\n\x1a\n",
            ".jpg": b"\xff\xd8\xff",
            ".jpeg": b"\xff\xd8\xff",
        }
        expected = signatures.get(suffix)
        if expected and not payload.startswith(expected):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "File content does not match extension")

    async def save(self, user_id: UUID, file: UploadFile) -> Path:
        self.validate_metadata(file)
        payload = await file.read()
        if len(payload) > settings.max_upload_mb * 1024 * 1024:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is too large")
        user_dir = settings.upload_dir / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(file.filename or "").suffix.lower()
        self.validate_payload(payload, suffix)
        path = user_dir / f"{uuid4()}{suffix}"
        path.write_bytes(payload)
        return path


class IngestionService:
    max_csv_rows = 5000

    def __init__(self, categorizer: CategorizationService | None = None) -> None:
        self.categorizer = categorizer or CategorizationService()

    def parse_csv(self, payload: bytes) -> list[TransactionCreate]:
        try:
            text = payload.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "CSV must be UTF-8 encoded") from exc
        reader = csv.DictReader(io.StringIO(text))
        rows: list[TransactionCreate] = []
        for line_number, raw in enumerate(reader, start=2):
            if len(rows) >= self.max_csv_rows:
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

    def extract_document_text(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            with pdfplumber.open(path) as pdf:
                return "\n".join(page.extract_text() or "" for page in pdf.pages)
        if suffix in {".png", ".jpg", ".jpeg"}:
            image = Image.open(path)
            return f"Image uploaded: {image.width}x{image.height}. OCR runtime available via pytesseract."
        return ""
