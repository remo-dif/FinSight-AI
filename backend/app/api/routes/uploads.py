from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_async_db
from app.core.security import require_role_async
from app.models.finance import UploadedFile
from app.models.user import User, UserRole
from app.schemas.uploads import UploadResponse
from app.services.document_ingestion import DocumentIngestionService

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    user: User = Depends(require_role_async(UserRole.USER, UserRole.ADMIN)),
    db: AsyncSession = Depends(get_async_db),
) -> UploadResponse:
    service = DocumentIngestionService()
    upload = await service.save_upload(user.id, file)
    record = UploadedFile(
        user_id=user.id,
        filename=upload.filename,
        content_type=upload.content_type,
        storage_path=upload.storage_uri,
        status="stored",
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)

    result = await service.ingest_upload(db, user.id, upload, record)
    record.status = result.status
    await db.commit()
    await db.refresh(record)
    return UploadResponse(
        file_id=record.id,
        status=record.status,
        imported=result.imported,
        indexed=result.indexed,
    )
