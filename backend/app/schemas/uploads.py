"""Schemas for upload and document-ingestion API responses."""

from uuid import UUID

from pydantic import BaseModel


class UploadResponse(BaseModel):
    file_id: UUID
    status: str
    imported: int
    indexed: int
