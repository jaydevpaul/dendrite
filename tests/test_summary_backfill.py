"""The summary backfill: find every message the queue missed, and summarize it.

What counts as missing is `find_unsummarized`'s decision and is tested with the
writer. These tests are about the run itself - the report it prints, that a dry
run spends nothing, and that one failing message does not stop the rest. A
summary is a real model call, so a run that skipped nothing it should have, or
repeated work it had already done, costs money every time it is used.
"""

from sqlalchemy import func, select

from app.backfill_embeddings import BackfillReport
from app.backfill_summaries import backfill
from app.llm.fake import FakeLLMError
from app.models.message_summary import MessageSummary
from tests.graph_builders import new_conversation, new_message, new_user


async def a_conversation(session):
    user = await new_user(session)
    return await new_conversation(session, user)


async def summary_count(session_factory):
    async with session_factory() as other:
        return await other.scalar(select(func.count()).select_from(MessageSummary))


async def test_a_dry_run_counts_and_writes_nothing(session, session_factory, llm):
    conversation = await a_conversation(session)
    await new_message(session, conversation, content="one")
    await new_message(session, conversation, content="two")
    await session.commit()

    report = await backfill(session_factory, llm, dry_run=True)

    assert report == BackfillReport(missing=2, filled=0, failed=0)
    assert llm.summarize_calls == []
    assert await summary_count(session_factory) == 0


async def test_a_run_fills_every_missing_message(session, session_factory, llm):
    conversation = await a_conversation(session)
    await new_message(session, conversation, content="one")
    await new_message(session, conversation, role="assistant", content="two")
    await new_message(session, conversation, role="assistant", content="  ")
    await session.commit()

    report = await backfill(session_factory, llm)

    assert report == BackfillReport(missing=2, filled=2, failed=0)
    assert await summary_count(session_factory) == 2


async def test_a_second_run_finds_nothing_left(session, session_factory, llm):
    conversation = await a_conversation(session)
    await new_message(session, conversation, content="one")
    await session.commit()
    await backfill(session_factory, llm)

    report = await backfill(session_factory, llm)

    assert report == BackfillReport(missing=0, filled=0, failed=0)
    assert len(llm.summarize_calls) == 1


async def test_one_failure_does_not_stop_the_rest(session, session_factory, llm):
    """A message the summarizer refuses is counted and skipped; the ones after
    it are still filled, and the next run will try the refused one again."""
    conversation = await a_conversation(session)
    await new_message(session, conversation, content="fine")
    await new_message(session, conversation, content="refused")
    await new_message(session, conversation, content="also fine")
    await session.commit()

    original = llm.summarize

    async def refuse_one(text, words):
        if text == "refused":
            raise FakeLLMError("scripted: refused")
        return await original(text, words)

    llm.summarize = refuse_one

    report = await backfill(session_factory, llm)

    assert report == BackfillReport(missing=3, filled=2, failed=1)
    assert await summary_count(session_factory) == 2

    llm.summarize = original
    assert (await backfill(session_factory, llm)).missing == 1


async def test_a_blank_answer_counts_as_a_failure(session, session_factory, llm):
    """Not as filled, and not silently skipped: it is reported, and the message
    is still missing on the next run."""
    conversation = await a_conversation(session)
    await new_message(session, conversation, content="one")
    await session.commit()

    async def blank(text, words):
        return ""

    llm.summarize = blank

    report = await backfill(session_factory, llm)

    assert report == BackfillReport(missing=1, filled=0, failed=1)
    assert await summary_count(session_factory) == 0
