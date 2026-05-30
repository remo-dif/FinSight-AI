from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.finance import UploadedFile
from app.models.user import User
from app.repositories.transactions import TransactionRepository
from app.services.audit import AuditService
from app.services.ingestion import IngestionService, SecureUploadService
from app.services.rag import RagService

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("")
async def upload_file(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    uploader = SecureUploadService()
    path = await uploader.save(user.id, file)
    record = UploadedFile(
        user_id=user.id,
        filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        storage_path=str(path),
        status="stored",
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    service = IngestionService()
    imported = 0
    indexed = 0
    if path.suffix.lower() == ".csv":
        transactions = service.parse_csv(path.read_bytes())
        imported = len(TransactionRepository(db).create_many(user.id, transactions))
        record.status = "processed"
    else:
        text = service.extract_document_text(path)
        indexed = RagService(db).index_text(user.id, "upload", record.id, text)
        record.status = "indexed"
    AuditService(db).record("file.upload", user.id, {"filename": record.filename, "status": record.status})
    db.commit()
    return {"file_id": str(record.id), "status": record.status, "imported": imported, "indexed": indexed}
