import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7
from app.models._shared import UUIDType


class User(Base):
    """The account a Conversation belongs to.

    Not one of the six entities in the decision record - it exists so
    Conversation.user_id has a real FK target. Extended from the original
    id-only stub with credentials per docs/auth_design.md section 5
    (decision record section 8.8).
    """

    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid7)
    email: Mapped[str] =  mapped_column(nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
