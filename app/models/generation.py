import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, CheckConstraint, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7
from app.models._shared import ALL_STRATEGIES_SQL, UUIDType


class Generation(Base):
    __tablename__ = "generation"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid7)
    user_message_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("message.id"), nullable=False
    )
    assistant_message_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("message.id"), nullable=False, unique=True
    )
    strategy_used: Mapped[str] = mapped_column(nullable=False)
    model_used: Mapped[str] = mapped_column(nullable=False)
    composed_context: Mapped[str] = mapped_column(nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            f"strategy_used IN {ALL_STRATEGIES_SQL}",
            name="ck_generation_strategy_used",
        ),
        Index("ix_generation_user_message_id", "user_message_id"),
    )
