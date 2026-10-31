from fastapi import APIRouter

from app.api.routes import auth, cases, chat, document_qa, transactions, uploads

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(cases.router)
api_router.include_router(transactions.router)
api_router.include_router(uploads.router)
api_router.include_router(chat.router)
api_router.include_router(document_qa.router)
api_router.include_router(document_qa.root_router)
