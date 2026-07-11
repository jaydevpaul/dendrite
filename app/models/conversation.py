import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, CheckConstraint, ForeignKey, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7
from app.models._shared import NON_SPAN_STRATEGIES_SQL, UUIDType


class Conversation(Base):
    __tablename__ = "conversation"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("user.id"), nullable=False)
    title: Mapped[str] = mapped_column(nullable=False, server_default=text("'Untitled'"))
    default_strategy: Mapped[str] = mapped_column(nullable=False)
    # Nullable: set after the first message exists. use_alter breaks the
    # conversation<->message circular FK so both tables can be created.
    root_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("message.id", use_alter=True, name="fk_conversation_root_message_id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            f"default_strategy IN {NON_SPAN_STRATEGIES_SQL}",
            name="ck_conversation_default_strategy",
        ),
    )
