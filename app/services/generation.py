"""Generating a reply: compose, open a blank row, stream, write once."""

import json
import logging

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func,update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.context.compose import Composition,compose_context
from app.core.config import settings
from app.core.db import async_session_factory
from app.llm.base import Completed,LLMClient,TextDelta

from app.models.conversation import Conversation
from app.models.edge import Edge
from app.models.generation import Generation
from app.models.message import Message

from app.services.ancestors import MessageNotFound
from app.services.message import get_message_in_conversation


logger = logging.getLogger(__name__)

GENERATION_FAILED = "generation failed"

class NotAUserMessage(Exception):
    """Generation was asked to reply to something that is not a user message."""

@dataclass(frozen=True)
class PreparedGeneration:
    """Everything Settled before the stream opens"""

    user_message_id:UUID
    assistant_message_id: UUID
    composition: Composition
    model: str

@dataclass(frozen=True)
class GenerationDone:
    """The terminal event of a run that finished."""
    generation_id:UUID
    input_tokens:int | None
    output_tokens: int | None
    degradations: list[str]


@dataclass(frozen=True)
class GenerationFailed:
    """The terminal event of a run that died. The cause is in the log."""
    detail: str


# One stream is zero or more TextDelta and then exactly one terminal event.
streamEvent = TextDelta | GenerationDone | GenerationFailed


async def start_generation(
    session:AsyncSession,
    conversation: Conversation,
    message_id: UUID,
    llm:LLMClient
):
    """Compose the context, then open a blank assistant row to stream into."""

    question = await get_message_in_conversation(session,conversation,message_id)

    if question is None:
        raise MessageNotFound(message_id)

    if question.role != "user":
        raise NotAUserMessage(message_id)

    composition = await compose_context(session, conversation,message_id, llm)

    assistant = Message(conversation_id=conversation.id,role="assistant",content="")
    session.add(assistant)
    # The edge needs an id to point at, and both rows still commit as one.
    await session.flush()

    # A reply continues the thread. The anchor lives on the branch edge above
    # the question and is not copied down.

    session.add(Edge(
        parent_message_id=question.id,
        child_message_id=assistant.id
    ))

    conversation.updated_at = func.now()

    await session.commit()

    return PreparedGeneration(
        user_message_id=question.id,
        assistant_message_id=assistant.id,
        composition=composition,
        model=settings.generation_model
    )

async def stream_generation(
        prepared: PreparedGeneration,
        llm: LLMClient,
        session_factory: async_sessionmaker[AsyncSession] = async_session_factory
):
    """Stream the reply, then write it and its record in one transaction."""

    context = prepared.composition.context
    completed: Completed | None = None


    try:
        async for event in llm.generate(context.system, context.messages):
            if isinstance(event,TextDelta):
                yield event
            else:
                completed = event 
    except Exception:
        logger.exception(
            "generation failed for assistant message %s",
            prepared.assistant_message_id
        )

        await _write_failure(prepared,session_factory)
        yield GenerationFailed(detail=GENERATION_FAILED)
        return

    if completed is None:
        logger.error(
            "generation ended with no completion for assistant message %s",
            prepared.assistant_message_id, 
        )
        await _write_failure(prepared, session_factory)
        yield GenerationFailed(detail=GENERATION_FAILED)
        return

    generation_id = await _write_completion(prepared, completed, session_factory)

    yield GenerationDone(
        generation_id=generation_id,
        input_tokens=completed.input_tokens,
        output_tokens=completed.output_tokens,
        degradations=list(context.degradations)
    )

def _generation_row(
        prepared: PreparedGeneration,
        model: str,
        input_tokens: int | None= None,
        output_tokens: int | None = None,
):

    """The record of one run."""

    return Generation(
        user_message_id=prepared.user_message_id,
        assistant_message_id=prepared.assistant_message_id,
        strategy_used=prepared.composition.context.strategy_used,
        model_used=model,

        composed_context=json.dumps(prepared.composition.context.as_payload()),
        input_tokens=input_tokens,
        output_tokens=output_tokens
    )

async def _write_completion(
    prepared: PreparedGeneration,
    completed:Completed,
    session_factory: async_sessionmaker[AsyncSession]
):
    """The reply and its record, in one transaction."""

    async with session_factory() as session:
        await session.execute(
            update(Message)
            .where(Message.id == prepared.assistant_message_id)
            .values(content=completed.text,updated_at = Message.created_at)
            .execution_options(synchronize_session=False)
        )

        generation = _generation_row(
            prepared=prepared,
            model=completed.model,
            input_tokens= completed.input_tokens,
            output_tokens=completed.output_tokens
        )

        session.add(generation)

        await session.commit()

        return generation.id

async def _write_failure(
    prepared: PreparedGeneration,
    session_factory: async_sessionmaker[AsyncSession],
):
    """The record of a run that died: no token counts, and the reply left blank."""

    async with session_factory() as session:
        session.add(_generation_row(prepared,prepared.model))
        await session.commit()



































