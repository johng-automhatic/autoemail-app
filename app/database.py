"""Async database engine and session management (lazy initialization)."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

# Lazy engine — created on first use, not at import time
_engine = None
_async_session = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            get_settings().database_url,
            echo=False,
            pool_size=5,
            max_overflow=10,
        )
    return _engine


def _get_session_maker():
    global _async_session
    if _async_session is None:
        _async_session = async_sessionmaker(
            _get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _async_session


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    """FastAPI dependency that yields an async DB session."""
    session_maker = _get_session_maker()
    async with session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
