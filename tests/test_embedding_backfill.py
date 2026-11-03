"""The backfill: find every message the queue missed, and embed it.

`find_unembedded` decides what counts as missing, so most of the tests are
about what it must leave out - blank messages, and messages already done by the
current model - because anything it wrongly includes is an embedder call on
every run, forever. `backfill` is then tested for its report and for carrying
on past a message that fails.
"""

from sqlalchemy import func, select

from app.backfill_embeddings import BackfillReport, backfill
from app.llm.fake import FakeLLMError
from app.models.message_embedding import MessageEmbedding
from app.services.embedding import find_unembedded
from tests.graph_builders import (
    new_conversation,
    new_embedding,
    new_message,
    new_user,
)


async def a_conversation(session):
    user = await new_user(session)
    return await new_conversation(session, user)


async def embedding_count(session_factory):
    async with session_factory() as other:
        return await other.scalar(select(func.count()).select_from(MessageEmbedding))


# --- what counts as missing -----------------------------------------------


async def test_finds_messages_with_no_embedding_oldest_first(session):
    conversation = await a_conversation(session)
    first = await new_message(session, conversation, content="first")
    second = await new_message(session, conversation, role="assistant", content="second")

    assert await find_unembedded(session) == [first.id, second.id]


async def test_a_message_already_embedded_is_not_missing(session):
    conversation = await a_conversation(session)
    done = await new_message(session, conversation, content="done")
    todo = await new_message(session, conversation, content="todo")
    await new_embedding(session, done)

    assert await find_unembedded(session) == [todo.id]


async def test_a_row_from_another_model_does_not_count(session):
    conversation = await a_conversation(session)
    message = await new_message(session, conversation, content="old vectors only")
    await new_embedding(session, message, model_used="some-older-embedder")

    assert await find_unembedded(session) == [message.id]


async def test_blank_and_whitespace_messages_are_not_missing(session):
    """The embed step skips these, so listing them would make every run report
    them as missing again, and they would never go away. Spaces are the case
    that matters: Postgres trims only the characters it is given."""
    conversation = await a_conversation(session)
    for blank in ["", "   ", "\n\t \r\n"]:
        await new_message(session, conversation, role="assistant", content=blank)
    real = await new_message(session, conversation, content="  has text  ")

    assert await find_unembedded(session) == [real.id]


# --- the run --------------------------------------------------------------


async def test_a_dry_run_counts_and_writes_nothing(session, session_factory, llm):
    conversation = await a_conversation(session)
    await new_message(session, conversation, content="one")
    await new_message(session, conversation, content="two")
    await session.commit()

    report = await backfill(session_factory, llm, dry_run=True)

    assert report == BackfillReport(missing=2, filled=0, failed=0)
    assert llm.embed_calls == []
    assert await embedding_count(session_factory) == 0


async def test_a_run_fills_every_missing_message(session, session_factory, llm):
    conversation = await a_conversation(session)
    await new_message(session, conversation, content="one")
    await new_message(session, conversation, content="two")
    await session.commit()

    report = await backfill(session_factory, llm)

    assert report == BackfillReport(missing=2, filled=2, failed=0)
    assert await embedding_count(session_factory) == 2


async def test_a_second_run_finds_nothing_left(session, session_factory, llm):
    conversation = await a_conversation(session)
    await new_message(session, conversation, content="one")
    await session.commit()
    await backfill(session_factory, llm)

    report = await backfill(session_factory, llm)

    assert report == BackfillReport(missing=0, filled=0, failed=0)
    assert len(llm.embed_calls) == 1


async def test_one_failure_does_not_stop_the_rest(session, session_factory, llm):
    """A message the embedder refuses is counted and skipped; the ones after it
    are still filled, and the next run will try the refused one again."""
    conversation = await a_conversation(session)
    await new_message(session, conversation, content="fine")
    await new_message(session, conversation, content="refused")
    await new_message(session, conversation, content="also fine")
    await session.commit()

    original = llm.embed

    async def refuse_one(text):
        if text == "refused":
            raise FakeLLMError("scripted: refused")
        return await original(text)

    llm.embed = refuse_one

    report = await backfill(session_factory, llm)

    assert report == BackfillReport(missing=3, filled=2, failed=1)
    assert await embedding_count(session_factory) == 2

    llm.embed = original
    assert (await backfill(session_factory, llm)).missing == 1
