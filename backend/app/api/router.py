from fastapi import APIRouter

from app.api.routes import auth, chat, transactions, uploads

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(transactions.router)
api_router.include_router(uploads.router)
api_router.include_router(chat.router)
