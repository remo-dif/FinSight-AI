from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.security import require_role_async
from app.models.finance import UploadedFile
from app.models.user import User, UserRole
from app.schemas.uploads import UploadedDocumentResponse, UploadResponse
from app.services.document_ingestion import DocumentIngestionService

router = APIRouter(prefix="/uploads", tags=["uploads"])
upload_user = require_role_async(UserRole.USER, UserRole.ADMIN)
UPLOAD_LIST_PAGE_SIZE = 100


@router.get("", response_model=list[UploadedDocumentResponse])
async def list_uploads(
    user: Annotated[User, Depends(upload_user)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
    limit: Annotated[int, Query(ge=1, le=UPLOAD_LIST_PAGE_SIZE)] = UPLOAD_LIST_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> list[UploadedDocumentResponse]:
    result = await db.scalars(
        select(UploadedFile)
        .where(UploadedFile.user_id == user.id)
        .order_by(UploadedFile.created_at, UploadedFile.id)
        .limit(limit)
        .offset(offset)
    )
    return [
        UploadedDocumentResponse(
            id=record.id,
            filename=record.filename,
            status=record.status,
            created_at=record.created_at,
        )
        for record in result
    ]


@router.post("", response_model=UploadResponse)
async def upload_file(
    file: Annotated[UploadFile, File()],
    user: Annotated[User, Depends(upload_user)],
    db: Annotated[AsyncSession, Depends(get_async_db)],
    import_currency: Annotated[str | None, Form()] = None,
) -> UploadResponse:
    user_id = user.id
    await db.rollback()  # End authentication's read transaction before I/O/provider calls.
    service = DocumentIngestionService()
    upload = None
    commit_attempted = False
    try:
        upload = await service.save_upload(user_id, file, stage_only=True)
        prepared = await service.prepare_upload(upload, import_currency)
        upload = await service.finalize_storage(user_id, upload)
        file_id = uuid4()
        record = UploadedFile(
            id=file_id,
            user_id=user_id,
            filename=upload.filename,
            content_type=upload.content_type,
            storage_path=upload.storage_uri,
            status=prepared.status,
        )
        db.add(record)
        await db.flush()
        result = await service.ingest_upload(db, user_id, upload, record, prepared)
        response = UploadResponse(
            file_id=file_id, status=result.status, imported=result.imported, indexed=result.indexed
        )
        commit_attempted = True
        await db.commit()
    except BaseException:
        rollback_succeeded = False
        try:
            await db.rollback()
            rollback_succeeded = True
        finally:
            if upload:
                if commit_attempted or not rollback_succeeded:
                    # A lost commit acknowledgement does not prove that the DB rolled back.
                    # Preserve final storage for reconciliation rather than risk data loss.
                    await service.release_upload(upload)
                else:
                    await service.cleanup_upload(upload)
        raise
    await service.release_upload(upload)
    return response
