from collections.abc import AsyncGenerator, Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
_async_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _async_database_url() -> str:
    if settings.database_url.startswith("postgresql+psycopg://"):
        return settings.database_url
    if settings.database_url.startswith("postgresql://"):
        return settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if settings.database_url.startswith("sqlite+pysqlite://"):
        return settings.database_url.replace("sqlite+pysqlite://", "sqlite+aiosqlite://", 1)
    return settings.database_url


def get_async_session_factory() -> async_sessionmaker[AsyncSession]:
    global _async_session_factory
    if _async_session_factory is None:
        async_engine = create_async_engine(_async_database_url(), pool_pre_ping=True)
        _async_session_factory = async_sessionmaker(
            bind=async_engine,
            autoflush=False,
            expire_on_commit=False,
        )
    return _async_session_factory


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    async_session_factory = get_async_session_factory()
    async with async_session_factory() as db:
        try:
            yield db
        except Exception:
            await db.rollback()
            raise
