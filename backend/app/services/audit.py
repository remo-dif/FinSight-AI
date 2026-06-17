from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.audit import AuditLog


class AuditService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def record(self, action: str, user_id: UUID | None = None, metadata: dict | None = None) -> None:
        self.db.add(AuditLog(action=action, user_id=user_id, metadata_json=metadata or {}))


class AsyncAuditService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record(
        self,
        action: str,
        user_id: UUID | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.db.add(AuditLog(action=action, user_id=user_id, metadata_json=metadata or {}))
