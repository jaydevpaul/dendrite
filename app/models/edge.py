import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, CheckConstraint, ForeignKey, Index, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import uuid7
from app.models._shared import ALL_STRATEGIES_SQL, UUIDType


class Edge(Base):
    __tablename__ = "edge"

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid7)
    parent_message_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("message.id"), nullable=False
    )
    # unique=True: one parent max per child message; also satisfies the
    # btree index section 9 calls for on this column.
    child_message_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("message.id"), nullable=False, unique=True
    )
    anchor_start: Mapped[int | None] = mapped_column(nullable=True)
    anchor_end: Mapped[int | None] = mapped_column(nullable=True)
    anchored_text: Mapped[str | None] = mapped_column(nullable=True)
    strategy_override: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            f"strategy_override IN {ALL_STRATEGIES_SQL} OR strategy_override IS NULL",
            name="ck_edge_strategy_override",
        ),
        CheckConstraint(
            "num_nonnulls(anchor_start, anchor_end, anchored_text) IN (0, 3)",
            name="ck_edge_anchor_all_or_nothing",
        ),
        CheckConstraint(
            "anchor_start IS NULL OR anchor_start >= 0",
            name="ck_edge_anchor_start_nonnegative",
        ),
        CheckConstraint(
            "anchor_start IS NULL OR anchor_end > anchor_start",
            name="ck_edge_anchor_valid_span",
        ),
        CheckConstraint(
            "anchored_text IS NULL OR anchored_text <> ''",
            name="ck_edge_anchored_text_nonempty",
        ),
        CheckConstraint(
            "strategy_override <> 'SpanOnly' OR anchor_start IS NOT NULL",
            name="ck_edge_span_only_needs_anchor",
        ),
        Index("ix_edge_parent_message_id", "parent_message_id"),
    )
