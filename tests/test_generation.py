"""Generating a reply: compose, open a blank row, stream, write once.

Every assertion about what was written reads through `session_factory` rather
than the test's own session. That is not fussiness - the whole write pattern
turns on two separate commits, and a second connection is the only thing that
can tell a committed row from one sitting in an open transaction.
"""

import asyncio
import json

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.llm.base import TextDelta
from app.llm.fake import DEFAULT_CHUNKS, DEFAULT_MODEL, FakeLLMClient
from app.models.conversation import Conversation
from app.models.edge import Edge
from app.models.generation import Generation
from app.models.message import Message
from app.services.ancestors import MessageNotFound
from app.services.generation import (
    GENERATION_FAILED,
    GenerationDone,
    GenerationFailed,
    NotAUserMessage,
    start_generation,
    stream_generation,
)
from tests.graph_builders import (
    a_deep_question,
    a_question,
    new_conversation,
    new_message,
    new_user,
)

SCRIPTED_FAILURE = "scripted failure"


# --- reading the database back -------------------------------------------


async def read_message(session_factory, message_id):
    async with session_factory() as session:
        return await session.get(Message, message_id)


async def read_generations(session_factory, user_message_id):
    async with session_factory() as session:
        result = await session.execute(
            select(Generation).where(Generation.user_message_id == user_message_id)
        )
        return list(result.scalars().all())


async def read_messages(session_factory, conversation):
    async with session_factory() as session:
        result = await session.execute(
            select(Message).where(Message.conversation_id == conversation.id)
        )
        return list(result.scalars().all())


async def read_edge_above(session_factory, message_id):
    async with session_factory() as session:
        result = await session.execute(
            select(Edge).where(Edge.child_message_id == message_id)
        )
        return result.scalar_one_or_none()


async def drain(stream):
    return [event async for event in stream]


# --- preparing: compose, then open a row to stream into -------------------


async def test_preparing_composes_from_the_user_message(session):
    """The blank row is a child of the question, so composing after inserting
    it would put the branch edge a level further up and answer with the
    conversation default. Preparing composes first, and this is what says so:
    the branch still resolves to its span."""
    conversation, question, _ = await a_question(
        session, default_strategy="FullInheritance"
    )

    prepared = await start_generation(
        session, conversation, question.id, FakeLLMClient()
    )

    assert prepared.composition.resolution.strategy == "SpanOnly"
    assert prepared.composition.context.strategy_used == "SpanOnly"


async def test_preparing_opens_a_blank_assistant_row_under_the_question(
    session, session_factory
):
    conversation, question, _ = await a_question(session)

    prepared = await start_generation(
        session, conversation, question.id, FakeLLMClient()
    )

    assistant = await read_message(session_factory, prepared.assistant_message_id)
    assert assistant.role == "assistant"
    assert assistant.content == ""

    edge = await read_edge_above(session_factory, prepared.assistant_message_id)
    assert edge.parent_message_id == question.id
    # A reply continues the thread; the anchor belongs to the branch above it.
    assert edge.anchor_start is None
    assert edge.strategy_override is None


async def test_the_blank_row_is_committed_before_the_stream_opens(
    session, session_factory
):
    """A row nobody else can see is no use: an in-flight generation is read off
    a blank assistant message, and a second tab is on a second connection."""
    conversation, question, _ = await a_question(session)

    prepared = await start_generation(
        session, conversation, question.id, FakeLLMClient()
    )

    assert await read_message(session_factory, prepared.assistant_message_id)
    assert not await read_generations(session_factory, question.id)


async def test_preparing_moves_the_conversation_to_the_top(session, session_factory):
    """The list is ordered by when a conversation last changed, and a reply
    landing in it is a change."""
    conversation, question, _ = await a_question(session)
    async with session_factory() as fresh:
        before = (await fresh.get(Conversation, conversation.id)).updated_at

    await start_generation(session, conversation, question.id, FakeLLMClient())

    async with session_factory() as fresh:
        after = (await fresh.get(Conversation, conversation.id)).updated_at

    assert after > before


async def test_generation_refuses_to_reply_to_an_assistant_message(
    session, session_factory
):
    """Replying to a reply is how the blank-row mistake gets made, and the
    guard sits here rather than in the route because this is the thing that
    creates the row being guarded against."""
    conversation, _, ancestors = await a_question(session)
    reply = ancestors[-1]
    before = len(await read_messages(session_factory, conversation))

    with pytest.raises(NotAUserMessage):
        await start_generation(session, conversation, reply.id, FakeLLMClient())

    assert len(await read_messages(session_factory, conversation)) == before


async def test_generation_refuses_a_message_from_another_conversation(
    session, session_factory
):
    conversation, _, _ = await a_question(session)
    stranger_user = await new_user(session, email="someone-else@example.com")
    other = await new_conversation(session, stranger_user)
    stranger = await new_message(session, other, "user", "not yours")
    await session.commit()
    before = len(await read_messages(session_factory, conversation))

    with pytest.raises(MessageNotFound):
        await start_generation(session, conversation, stranger.id, FakeLLMClient())

    assert len(await read_messages(session_factory, conversation)) == before
    assert not await read_generations(session_factory, stranger.id)


# --- streaming, then one write -------------------------------------------


async def test_the_stream_yields_every_chunk_and_then_finishes(
    session, session_factory
):
    conversation, question, _ = await a_question(session)
    llm = FakeLLMClient()
    prepared = await start_generation(session, conversation, question.id, llm)

    events = await drain(stream_generation(prepared, llm, session_factory))

    assert [event.text for event in events[:-1]] == list(DEFAULT_CHUNKS)
    assert isinstance(events[-1], GenerationDone)


async def test_the_reply_is_written_once_at_completion(session, session_factory):
    """One UPDATE, with `updated_at` pinned back to `created_at`. Left to the
    column's own default it would move on this write, and an edited message
    would then be indistinguishable from a generated one - permanently, and
    anchor repair is what keys off that difference."""
    conversation, question, _ = await a_question(session)
    llm = FakeLLMClient()
    prepared = await start_generation(session, conversation, question.id, llm)

    await drain(stream_generation(prepared, llm, session_factory))

    assistant = await read_message(session_factory, prepared.assistant_message_id)
    assert assistant.content == "".join(DEFAULT_CHUNKS)
    assert assistant.updated_at == assistant.created_at


async def test_nothing_is_written_while_the_stream_is_open(session, session_factory):
    """The stream is buffered, not persisted chunk by chunk. Anchors are offsets
    into text, so an offset into a message that is still growing describes
    nothing - a message is only ever blank or final."""
    conversation, question, _ = await a_question(session)
    gate = asyncio.Event()
    llm = FakeLLMClient(gate=gate)
    prepared = await start_generation(session, conversation, question.id, llm)

    stream = stream_generation(prepared, llm, session_factory)
    first = asyncio.ensure_future(anext(stream))

    # generate() records the call before it waits, so this is the stream having
    # genuinely started rather than a guess at the scheduler.
    while not llm.calls:
        await asyncio.sleep(0)

    held = await read_message(session_factory, prepared.assistant_message_id)
    assert held.content == ""
    assert not await read_generations(session_factory, question.id)

    gate.set()
    assert isinstance(await first, TextDelta)
    events = await drain(stream)

    assert isinstance(events[-1], GenerationDone)
    written = await read_message(session_factory, prepared.assistant_message_id)
    assert written.content == "".join(DEFAULT_CHUNKS)


async def test_the_generation_row_records_what_ran(session, session_factory):
    conversation, question, _ = await a_question(session)
    llm = FakeLLMClient()
    prepared = await start_generation(session, conversation, question.id, llm)

    events = await drain(stream_generation(prepared, llm, session_factory))
    done = events[-1]

    (generation,) = await read_generations(session_factory, question.id)
    assert generation.id == done.generation_id
    assert generation.assistant_message_id == prepared.assistant_message_id
    assert generation.strategy_used == "SpanOnly"
    # The provider's own numbers and its own model id, not a local count and
    # not the configured name - these are the billed figures.
    assert generation.model_used == DEFAULT_MODEL
    assert generation.input_tokens == done.input_tokens
    assert generation.output_tokens == done.output_tokens
    assert generation.input_tokens > 0


async def test_the_stored_context_is_the_payload_that_was_sent(
    session, session_factory
):
    """Stored as JSON so a past generation can be replayed by resending it. A
    rendered transcript would only be readable, not runnable."""
    conversation, question, _ = await a_question(session)
    llm = FakeLLMClient()
    prepared = await start_generation(session, conversation, question.id, llm)

    await drain(stream_generation(prepared, llm, session_factory))

    (generation,) = await read_generations(session_factory, question.id)
    stored = json.loads(generation.composed_context)

    assert set(stored) == {"system", "messages"}
    assert stored == prepared.composition.context.as_payload()
    # And what was stored is what the client was actually handed.
    (call,) = llm.calls
    assert stored["system"] == call.system
    assert stored["messages"] == [
        {"role": turn.role, "content": turn.content} for turn in call.messages
    ]


async def test_a_degraded_run_is_recorded_as_the_arm_that_ran(
    session, session_factory
):
    """Retrieval was asked for and plain decay is what composed the prompt, so
    that is what the row says. The eval spots a degraded run by finding the
    strategy it asked for disagreeing with the one stored - which only works if
    the column is the record and not the intent."""
    conversation, question, _ = await a_deep_question(
        session, default_strategy="HierarchicalDecayWithRetrieval"
    )
    llm = FakeLLMClient(fail_on_embed=True)
    prepared = await start_generation(session, conversation, question.id, llm)

    await drain(stream_generation(prepared, llm, session_factory))

    (generation,) = await read_generations(session_factory, question.id)
    assert prepared.composition.resolution.strategy == (
        "HierarchicalDecayWithRetrieval"
    )
    assert generation.strategy_used == "HierarchicalDecay"


# --- the failure path ----------------------------------------------------


async def test_a_failed_generation_still_writes_its_row(session, session_factory):
    """With null token counts, and the composed context preserved - it is the
    only surviving record of what was attempted."""
    conversation, question, _ = await a_question(session)
    llm = FakeLLMClient(fail_after_chunk=1)
    prepared = await start_generation(session, conversation, question.id, llm)

    events = await drain(stream_generation(prepared, llm, session_factory))

    assert isinstance(events[0], TextDelta)
    assert isinstance(events[-1], GenerationFailed)

    (generation,) = await read_generations(session_factory, question.id)
    assert generation.input_tokens is None
    assert generation.output_tokens is None
    assert json.loads(generation.composed_context)["messages"]
    # The provider never reported a model, and the column cannot be null, so
    # the configured name is the best answer available.
    assert generation.model_used == settings.generation_model


async def test_a_failed_generation_leaves_the_reply_blank(session, session_factory):
    """Nothing is deleted - regeneration writes a new row rather than reusing
    this one, and deleting would take the edge and the evidence with it. The
    partial text the client already saw is discarded, so the row is blank and
    still reads as in-flight until someone asks for a Generation row."""
    conversation, question, _ = await a_question(session)
    llm = FakeLLMClient(fail_after_chunk=1)
    prepared = await start_generation(session, conversation, question.id, llm)

    await drain(stream_generation(prepared, llm, session_factory))

    assistant = await read_message(session_factory, prepared.assistant_message_id)
    assert assistant.content == ""
    assert assistant.updated_at == assistant.created_at
    assert await read_edge_above(session_factory, prepared.assistant_message_id)


async def test_the_failure_detail_does_not_carry_the_provider_error(
    session, session_factory, caplog
):
    """Provider messages can carry request ids and account details, and this
    one goes to a browser. The real exception goes to the log instead."""
    conversation, question, _ = await a_question(session)
    llm = FakeLLMClient(fail_after_chunk=0)
    prepared = await start_generation(session, conversation, question.id, llm)

    events = await drain(stream_generation(prepared, llm, session_factory))

    assert events == [GenerationFailed(detail=GENERATION_FAILED)]
    assert SCRIPTED_FAILURE not in events[0].detail
    assert SCRIPTED_FAILURE in caplog.text


async def test_one_user_message_can_carry_several_generations(
    session, session_factory
):
    """Regeneration, and the eval running five strategies against one question.
    Each run gets its own assistant message, which is what the unique
    constraint is on - not the user message."""
    conversation, question, _ = await a_question(session)

    first = await start_generation(session, conversation, question.id, FakeLLMClient())
    await drain(stream_generation(first, FakeLLMClient(), session_factory))
    second = await start_generation(session, conversation, question.id, FakeLLMClient())
    await drain(stream_generation(second, FakeLLMClient(), session_factory))

    assert first.assistant_message_id != second.assistant_message_id
    generations = await read_generations(session_factory, question.id)
    assert len(generations) == 2
    assert len({generation.assistant_message_id for generation in generations}) == 2
