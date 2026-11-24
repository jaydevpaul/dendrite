"""Summaries: writing them in the background, and reading them back out.

The writer runs in the background worker after a message is saved, never
inside a request. The reader is used during context composition, and is
written so that a summary not having arrived yet is not a failure.
"""


from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import AsyncSession


from app.core.config import settings
from app.llm.base import LLMClient
from app.models.message import Message
from app.models.message_summary import MessageSummary

class EmptySummary(Exception):
    """The model answered, but with nothing."""

def summary_word_target(text:str):
    """How many words this message's summary may use."""

    words =round(len(text.split())*settings.summary_ratio)
    return max(settings.summary_min_words,min(words,settings.summary_max_words))

def _has_summary(message_id,model:str):
    """True when this message already has a usable summary from this model."""

    return (
        select(MessageSummary.id)
        .where(
            MessageSummary.message_id==message_id,
            MessageSummary.model_used==model,
            func.btrim(MessageSummary.summary_text," \t\r\n") != ""
        )
    ).exists()

async def summarize_message(session:AsyncSession,llm:LLMClient,message_id:UUID):
    """Summarize one message, unless there is nothing to do."""

    message = await session.get(Message,message_id)

    if message is None or not message.content.strip():
        return False

    model = settings.summarization_model

    if await session.scalar(select(_has_summary(message_id,model))):
        return False

    summary = await llm.summarize(message.content, summary_word_target(message.content))

    if not summary.strip():
        raise EmptySummary(f"the model returned no summary for message {message_id}")


    session.add(
        MessageSummary(message_id=message_id, summary_text=summary, model_used=model)
    )

    await session.commit()
    return True  

async def find_unsummarized(session: AsyncSession):
    """Ids of every message with text but no usable summary from the current model."""
    model = settings.summarization_model

    result = await session.scalars(
        select(Message.id)
        .where(
            func.btrim(Message.content, " \t\r\n") != "",
            ~_has_summary(Message.id, model),
        )
        .order_by(Message.created_at, Message.id)

    )

    return list(result)

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

    query = select(MessageSummary.message_id, MessageSummary.summary_text).where(
        MessageSummary.message_id.in_(ids),
        # btrim defaults to trimming spaces and nothing else, so the set is
        # spelled out - a summariser that returns a bare newline has produced
        # nothing, and this is what says so.
        func.btrim(MessageSummary.summary_text, " \t\r\n") != "",
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




























