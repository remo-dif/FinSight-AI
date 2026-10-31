"""Schemas for upload and document-ingestion API responses."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class UploadResponse(BaseModel):
    file_id: UUID
    status: str
    imported: int
    indexed: int


class UploadedDocumentResponse(BaseModel):
    id: UUID
    filename: str
    status: str
    created_at: datetime
