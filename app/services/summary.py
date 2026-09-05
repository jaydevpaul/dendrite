"""Reading summaries back out for context composition.

Writing them is a background job that does not exist yet; this is the read
side, and it is written so that the absence of that job is not a failure.
"""

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message_summary import MessageSummary


async def load_summaries(
        session: AsyncSession,
        message_ids: Iterable[UUID],
        model:str | None = None
):
    """The current summary for each of these messages, as a map.

    Ids in, map out, one query for the whole chain. Fetching per ancestor
    inside the composition loop would be one round trip per level, and
    composition has one to two seconds to do everything in.

    A message with no summary is simply absent from the map. Summarizing runs
    in the background after a message is written, so a recent ancestor having
    no row yet is the ordinary state rather than a fault - the caller sends its
    full text instead, which costs more tokens and stays correct.
    """

    ids = list(message_ids)

    if not ids:
        return {}

    query = (
        select(MessageSummary.message_id, MessageSummary.summary_text)
        .where(MessageSummary.message_id.in_(ids))
    )

    if model is not None:
        query = query.where(MessageSummary.model_used == model)

    result = await session.execute(
        query.distinct(MessageSummary.message_id).order_by(
            MessageSummary.message_id,
            MessageSummary.created_at.desc(),
            MessageSummary.id.desc()
        )
    )

    return {message_id: text for message_id, text in result.all()}