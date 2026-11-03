"""Writing embeddings. Runs in the background worker, never inside a request."""

from uuid import UUID

from sqlalchemy import select,func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.llm.base import LLMClient
from app.models.message import Message
from app.models.message_embedding import MessageEmbedding

async def embed_message(session: AsyncSession, llm: LLMClient, message_id: UUID):
    """Embed one message, unless there is nothing to embed or it is already done.

    Returns True if a row was written. Running it twice on the same message is
    harmless, which is what lets a retried job and the backfill both call it.
    """

    message = await session.get(Message,message_id)

    # Deleted before the job ran, or a reply left blank because generation
    # failed. Neither has any text worth a vector.

    if message is None or not message.content.strip():
        return False

    model = settings.embedding_model

    already = await session.scalar(
        select(MessageEmbedding.id)
        .where(
            MessageEmbedding.message_id==message_id,
            MessageEmbedding.model_used==model
        )
        .limit(1)
    )

    if already is not None:
        return False

    vector =  await llm.embed(message.content);


    session.add(
        MessageEmbedding(
            message_id=message_id,
            embedding=vector,
            model_used=model
        )
    )

    await session.commit()

    return True;


async def find_unembedded(session: AsyncSession):
    """Ids of every message with text but no embedding from the current model."""

    model = settings.embedding_model

    has_embedding = (
        select(MessageEmbedding.id)
        .where(
            MessageEmbedding.message_id==Message.id,
            MessageEmbedding.model_used==model,
        )
        .exists()
    )

    result = await session.scalars(
        select(Message.id)
        .where(
            # btrim trims only spaces unless told which characters to trim.
            func.btrim(Message.content," \t\r\n")!="",
            ~has_embedding,
        )
        .order_by(Message.created_at,Message.id)
    )

    return list(result)

