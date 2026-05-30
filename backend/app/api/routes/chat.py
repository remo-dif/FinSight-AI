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

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    session = None
    if payload.session_id:
        session = db.scalar(
            select(ChatSession).where(
                ChatSession.id == payload.session_id,
                ChatSession.user_id == user.id,
            )
        )
        if session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat session not found")
    if session is None:
        session = ChatSession(user_id=user.id, title=payload.message[:80])
        db.add(session)
        db.flush()
        db.refresh(session)

    tools = FinanceToolLayer(FinanceAnalyticsService(TransactionRepository(db)))
    state = OrchestratorAgent(tools).run({"user_id": user.id, "message": payload.message})

    db.add_all(
        [
            ChatMessage(session_id=session.id, role="user", content=payload.message),
            ChatMessage(session_id=session.id, role="assistant", content=state["final_answer"]),
        ]
    )
    AuditService(db).record("ai.chat", user.id, {"intent": state["intent"]})
    db.commit()
    return ChatResponse(
        session_id=session.id,
        answer=state["final_answer"],
        review=state["review"],
        tool_results=state["tool_results"],
    )
