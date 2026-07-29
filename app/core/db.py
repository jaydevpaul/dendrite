from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase , registry

from app.core.config import settings
from sqlalchemy import Text


class Base(DeclarativeBase):
    type_annotation_map = {str: Text}

#created once at import time. Holds a connection pool to db.Its lazy no connection until first query.
engine: AsyncEngine = create_async_engine(settings.database_url, echo=settings.db_echo)

#A callable that produces AsyncSession objects bound to that engine.
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding one AsyncSession per request."""
    async with async_session_factory() as session:
        yield session
