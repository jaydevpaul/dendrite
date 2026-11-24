"""Writing one message's summary - the job the background worker runs.

Like the embedding writer, it is called with nothing but an id, possibly long
after the message was written and possibly twice. Most of these tests are the
cases where it must do nothing, decided before the model is called, because
the model call is the part that costs money. The rest pin down how long a
summary is allowed to be, and what happens when the model hands back nothing.
"""

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.ids import uuid7
from app.llm.fake import FakeLLMError
from app.models.message_summary import MessageSummary
from app.services.summary import (
    EmptySummary,
    find_unsummarized,
    load_summaries,
    summarize_message,
    summary_word_target,
)
from tests.graph_builders import (
    new_conversation,
    new_message,
    new_summary,
    new_user,
)


def words(n):
    return " ".join(f"w{i}" for i in range(n))


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
            select(MessageSummary).where(MessageSummary.message_id == message_id)
        )
        return list(result.scalars())


# --- how long a summary may be ------------------------------------------------


def test_a_short_message_gets_the_floor():
    """15% of a ten-word question is one or two words, which is no summary."""
    assert summary_word_target(words(10)) == settings.summary_min_words


def test_a_mid_length_reply_gets_its_share():
    assert summary_word_target(words(600)) == round(600 * settings.summary_ratio)


def test_a_very_long_reply_is_held_to_the_ceiling():
    assert summary_word_target(words(5000)) == settings.summary_max_words


def test_a_longer_message_never_gets_a_shorter_allowance():
    targets = [summary_word_target(words(n)) for n in range(0, 3000, 50)]

    assert targets == sorted(targets)


def test_the_knobs_come_from_config(monkeypatch):
    """They are there for the eval to tune, so changing them must change this."""
    monkeypatch.setattr(settings, "summary_ratio", 0.5)
    monkeypatch.setattr(settings, "summary_min_words", 5)
    monkeypatch.setattr(settings, "summary_max_words", 1000)

    assert summary_word_target(words(100)) == 50
    assert summary_word_target(words(4)) == 5
    assert summary_word_target(words(4000)) == 1000


# --- writing ------------------------------------------------------------------


async def test_writes_one_committed_row_from_the_message_text(
    session, session_factory, llm
):
    message = await a_message(session)

    written = await summarize_message(session, llm, message.id)

    assert written is True
    assert llm.summarize_calls == [
        (message.content, summary_word_target(message.content))
    ]

    rows = await rows_for(session_factory, message.id)
    assert len(rows) == 1
    assert rows[0].model_used == settings.summarization_model
    assert rows[0].summary_text == await llm.summarize(
        message.content, summary_word_target(message.content)
    )


async def test_a_long_reply_is_given_a_bigger_allowance_than_a_question(
    session, llm
):
    """The reason the allowance is a share rather than a fixed length."""
    user = await new_user(session)
    conversation = await new_conversation(session, user)
    question = await new_message(session, conversation, content=words(20))
    reply = await new_message(
        session, conversation, role="assistant", content=words(1000)
    )
    await session.commit()

    await summarize_message(session, llm, question.id)
    await summarize_message(session, llm, reply.id)

    (_, question_words), (_, reply_words) = llm.summarize_calls
    assert reply_words > question_words


async def test_an_assistant_reply_is_summarized_too(session, session_factory, llm):
    """Decay summarizes every older level, and replies are most of them."""
    reply = await a_message(session, role="assistant", content="Recall costs latency.")

    assert await summarize_message(session, llm, reply.id) is True
    assert len(await rows_for(session_factory, reply.id)) == 1


async def test_the_written_summary_is_what_the_reader_returns(session, llm):
    """The writer and the reader have to agree on the model id, or every
    summary written is one the reader filters out."""
    message = await a_message(session)
    await summarize_message(session, llm, message.id)

    summaries = await load_summaries(
        session, [message.id], model=settings.summarization_model
    )

    assert summaries[message.id].startswith("Summary: ")


# --- doing nothing ------------------------------------------------------------


async def test_a_second_run_writes_nothing_and_calls_nothing(
    session, session_factory, llm
):
    """A retried job and the backfill both re-run this on messages that may
    already be done."""
    message = await a_message(session)
    await summarize_message(session, llm, message.id)

    again = await summarize_message(session, llm, message.id)

    assert again is False
    assert len(llm.summarize_calls) == 1
    assert len(await rows_for(session_factory, message.id)) == 1


async def test_a_deleted_message_is_skipped(session, llm):
    assert await summarize_message(session, llm, uuid7()) is False
    assert llm.summarize_calls == []


@pytest.mark.parametrize("content", ["", "   ", " \n\t "])
async def test_a_blank_message_is_skipped(session, session_factory, llm, content):
    """The blank assistant row left behind when a generation fails."""
    message = await a_message(session, role="assistant", content=content)

    assert await summarize_message(session, llm, message.id) is False
    assert llm.summarize_calls == []
    assert await rows_for(session_factory, message.id) == []


async def test_a_summary_from_another_model_does_not_count(
    session, session_factory, llm
):
    """Changing the summarization model has to re-summarize, or the reader -
    which filters on the current model - would find nothing for old messages."""
    message = await a_message(session)
    await new_summary(session, message, model_used="some-older-model")
    await session.commit()

    assert await summarize_message(session, llm, message.id) is True
    assert len(await rows_for(session_factory, message.id)) == 2


async def test_a_blank_existing_summary_does_not_count(session, session_factory, llm):
    """The reader skips blank rows, so treating one as done would leave the
    message without a summary for good."""
    message = await a_message(session)
    await new_summary(
        session, message, summary_text=" \n ", model_used=settings.summarization_model
    )
    await session.commit()

    assert await summarize_message(session, llm, message.id) is True


# --- failing ------------------------------------------------------------------


async def test_a_blank_answer_raises_and_writes_nothing(
    session, session_factory, llm, monkeypatch
):
    """Raising is what gets the job retried and the backfill to report it. A
    stored blank row would mark the message done and nothing would retry."""
    message = await a_message(session)

    async def blank(text, words):
        return "  \n"

    monkeypatch.setattr(llm, "summarize", blank)

    with pytest.raises(EmptySummary):
        await summarize_message(session, llm, message.id)

    assert await rows_for(session_factory, message.id) == []


async def test_a_model_failure_propagates_and_writes_nothing(
    session, session_factory, llm
):
    """The worker turns the error into a retry; swallowing it here would
    hide the outage."""
    message = await a_message(session)
    llm.fail_on_summarize = True

    with pytest.raises(FakeLLMError):
        await summarize_message(session, llm, message.id)

    assert await rows_for(session_factory, message.id) == []


# --- finding what is missing --------------------------------------------------


async def test_find_unsummarized_lists_exactly_the_ones_still_to_do(session, llm):
    user = await new_user(session)
    conversation = await new_conversation(session, user)
    done = await new_message(session, conversation, content="already summarized")
    todo = await new_message(session, conversation, content="not yet")
    stale = await new_message(session, conversation, content="old model only")
    blank_row = await new_message(session, conversation, content="blank summary only")
    await new_message(session, conversation, role="assistant", content="   ")

    await new_summary(session, done, model_used=settings.summarization_model)
    await new_summary(session, stale, model_used="some-older-model")
    await new_summary(
        session, blank_row, summary_text="", model_used=settings.summarization_model
    )
    await session.commit()

    missing = await find_unsummarized(session)

    assert set(missing) == {todo.id, stale.id, blank_row.id}


async def test_find_unsummarized_is_oldest_first(session):
    user = await new_user(session)
    conversation = await new_conversation(session, user)
    first = await new_message(session, conversation, content="first")
    second = await new_message(session, conversation, content="second")
    await session.commit()

    assert await find_unsummarized(session) == [first.id, second.id]
