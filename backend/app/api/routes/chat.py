from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.orchestrator import OrchestratorAgent
from app.agents.tools import FinanceToolLayer
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.chat import ChatMessage, ChatSession
from app.models.user import User
from app.repositories.transactions import TransactionRepository
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.analytics import FinanceAnalyticsService
from app.services.audit import AuditService
from app.services.llm import LLMService
from app.services.rag import RagService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
):
    user_id = user.id
    session = None
    if payload.session_id:
        session = db.scalar(
            select(ChatSession).where(
                ChatSession.id == payload.session_id,
                ChatSession.user_id == user_id,
            )
        )
        if session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat session not found")
    tools = FinanceToolLayer(FinanceAnalyticsService(TransactionRepository(db)))
    rag_service = RagService(db)
    llm_service = LLMService()
    try:
        state = OrchestratorAgent(tools, rag_service, llm_service).run(
            {
                "user_id": user_id,
                "message": payload.message,
                "currency": payload.currency,
                "release_database": db.rollback,
            }
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    # Persist the complete turn atomically only after all provider calls finish.
    # Recheck ownership because the earlier read transaction has ended.
    if payload.session_id:
        session = db.scalar(
            select(ChatSession).where(
                ChatSession.id == payload.session_id,
                ChatSession.user_id == user_id,
            )
        )
        if session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat session not found")
    else:
        session = ChatSession(user_id=user_id, title=payload.message[:80])
        db.add(session)
        db.flush()

    db.add_all(
        [
            ChatMessage(session_id=session.id, role="user", content=payload.message),
            ChatMessage(session_id=session.id, role="assistant", content=state["final_answer"]),
        ]
    )
    AuditService(db).record("ai.chat", user_id, {"intent": state["intent"]})
    session_id = session.id
    db.commit()
    return ChatResponse(
        session_id=session_id,
        answer=state["final_answer"],
        review=state["review"],
        tool_results=state["tool_results"],
    )
