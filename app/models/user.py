import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7
from app.models._shared import UUIDType


class User(Base):
    """Minimal stub, not one of the six entities in the decision record.

    Exists only so Conversation.user_id has a real FK target ahead of the
    auth design (decision record section 12). Expand or replace when auth lands.
    """

    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
