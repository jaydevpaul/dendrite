import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7
from app.models._shared import UUIDType


class MessageSummary(Base):
    __tablename__ = "message_summary"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid7)
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("message.id", ondelete="CASCADE"), nullable=False
    )
    summary_text: Mapped[str] = mapped_column(nullable=False)
    model_used: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_message_summary_message_id", "message_id"),)
