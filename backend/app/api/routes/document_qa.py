from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.schemas.document_qa import (
    DocumentQuestionRequest,
    DocumentQuestionResponse,
)
from app.services.document_qa import DocumentQAService

router = APIRouter(prefix="/documents", tags=["documents"])
root_router = APIRouter(tags=["documents"])


@router.post("/ask", response_model=DocumentQuestionResponse)
@router.post("/qa", response_model=DocumentQuestionResponse)
@router.post("/question-answer", response_model=DocumentQuestionResponse)
@root_router.post("/document-qa", response_model=DocumentQuestionResponse)
@root_router.post("/document-question-answer", response_model=DocumentQuestionResponse)
def ask_document_question(
    payload: DocumentQuestionRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentQuestionResponse:
    question = payload.question or payload.message
    if not question or not question.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Question is required")
    service = DocumentQAService(db, user.id)
    result = service.answer(
        question,
        document_ids=(
            payload.document_ids if payload.document_ids is not None else payload.document_scope
        ),
        limit=payload.limit,
        min_score=payload.min_score,
    )
    return DocumentQuestionResponse(**result)
