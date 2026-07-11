import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import TIMESTAMP, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7
from app.models._shared import UUIDType


class MessageEmbedding(Base):
    __tablename__ = "message_embedding"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid7)
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("message.id"), nullable=False
    )
    embedding: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    model_used: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_message_embedding_message_id", "message_id"),
        Index(
            "ix_message_embedding_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
