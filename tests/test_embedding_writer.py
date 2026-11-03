"""Writing one message's embedding - the job the background worker runs.

The function is called with nothing but an id, from a process that did not
write the message, possibly long after it was written and possibly twice. Most
of what is tested here is the set of cases where it must quietly do nothing:
the message is gone, the message is blank, or the row already exists. Each of
those has to be decided before the embedder is called, because the embedder is
the part that costs money.
"""

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.core.ids import uuid7
from app.llm.fake import FakeLLMError, fake_vector
from app.models.message_embedding import MessageEmbedding
from app.services.embedding import embed_message
from tests.graph_builders import (
    new_conversation,
    new_embedding,
    new_message,
    new_user,
)


async def a_message(session, role="user", content="how does recall trade against speed?"):
    user = await new_user(session)
    conversation = await new_conversation(session, user)
    message = await new_message(session, conversation, role=role, content=content)
    await session.commit()
    return message


async def rows_for(session_factory, message_id):
    """What a second connection sees - only what was really committed."""
    async with session_factory() as other:
        result = await other.execute(
            select(MessageEmbedding).where(MessageEmbedding.message_id == message_id)
        )
        return list(result.scalars())


async def test_writes_one_committed_row_from_the_message_text(
    session, session_factory, llm
):
    message = await a_message(session)

    written = await embed_message(session, llm, message.id)

    assert written is True
    assert llm.embed_calls == [message.content]

    rows = await rows_for(session_factory, message.id)
    assert len(rows) == 1
    assert rows[0].model_used == settings.embedding_model
    assert list(rows[0].embedding) == pytest.approx(fake_vector(message.content))


async def test_an_assistant_reply_is_embedded_too(session, session_factory, llm):
    """Retrieval ranks every ancestor that was summarised, and replies are most
    of them. Embedding only the user's side would leave half the chain
    unreachable."""
    reply = await a_message(session, role="assistant", content="Recall costs latency.")

    assert await embed_message(session, llm, reply.id) is True
    assert len(await rows_for(session_factory, reply.id)) == 1


async def test_a_second_run_writes_nothing_and_calls_nothing(
    session, session_factory, llm
):
    """A retried job and the backfill both re-run this on messages that may
    already be done."""
    message = await a_message(session)
    await embed_message(session, llm, message.id)

    again = await embed_message(session, llm, message.id)

    assert again is False
    assert len(llm.embed_calls) == 1
    assert len(await rows_for(session_factory, message.id)) == 1


@pytest.mark.parametrize("content", ["", "   ", "\n\t  \r\n"])
async def test_a_blank_message_is_skipped_without_a_call(
    session, session_factory, llm, content
):
    """A reply whose generation failed stays blank. A vector of nothing would
    sit in the index and match nothing usefully."""
    blank = await a_message(session, role="assistant", content=content)

    assert await embed_message(session, llm, blank.id) is False
    assert llm.embed_calls == []
    assert await rows_for(session_factory, blank.id) == []


async def test_a_message_deleted_before_the_job_ran_is_skipped(session, llm):
    assert await embed_message(session, llm, uuid7()) is False
    assert llm.embed_calls == []


async def test_a_row_from_another_model_does_not_count_as_done(
    session, session_factory, llm
):
    """Vectors from two models live in different spaces and retrieval never
    compares across them, so an old model's row leaves this one still to do."""
    message = await a_message(session)
    await new_embedding(session, message, model_used="some-older-embedder")
    await session.commit()

    assert await embed_message(session, llm, message.id) is True

    models = {row.model_used for row in await rows_for(session_factory, message.id)}
    assert models == {"some-older-embedder", settings.embedding_model}


async def test_an_embedder_failure_raises_and_writes_nothing(
    session, session_factory, llm
):
    """The error has to escape. Swallowing it would tell the queue the job
    succeeded, and it would never be retried."""
    message = await a_message(session)
    llm.fail_on_embed = True

    with pytest.raises(FakeLLMError):
        await embed_message(session, llm, message.id)

    async with session_factory() as other:
        count = await other.scalar(select(func.count()).select_from(MessageEmbedding))
    assert count == 0
