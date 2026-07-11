from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase , registry

from app.core.config import settings
from sqlalchemy import Text


class Base(DeclarativeBase):
    type_annotation_map = {str: Text}   


engine: AsyncEngine = create_async_engine(settings.database_url, echo=settings.db_echo)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)
