"""Queueing summary jobs from the routes, and the worker job that runs them.

Same shape as the embedding queue tests, and run against the same recording
queue. Every place a message is written queues both jobs through one function,
so most of what is checked here is that the two lists never drift apart.
"""

from uuid import UUID

import pytest
from arq import Retry
from sqlalchemy import select

from app import worker
from app.core.config import settings
from app.models.message_summary import MessageSummary
from tests.test_generate_route import a_question, only, sse
from tests.test_message_routes import ALICE, new_conversation, post_message, signup

JOB = "summarize_message_job"
EMBED = "embed_message_job"


def queued(queue, job=JOB):
    return [message_id for name, message_id in queue.jobs if name == job]


def generate_url(conversation_id, message_id):
    return f"/conversations/{conversation_id}/messages/{message_id}/generate"


# --- the name the routes queue under --------------------------------------


def test_the_queued_name_is_a_function_the_worker_runs():
    """arq finds the job by this string. A rename on one side only would queue
    jobs no worker ever picks up, and nothing anywhere would raise."""
    assert JOB in {function.__name__ for function in worker.WorkerSettings.functions}


# --- writing a message ----------------------------------------------------


async def test_a_saved_message_is_queued_for_summarizing(client, queue):
    await signup(client, ALICE)
    conversation_id = await new_conversation(client)

    response = await post_message(client, conversation_id, role="user", content="hi")

    message_id = UUID(response.json()["message"]["id"])
    assert queued(queue) == [message_id]


async def test_every_message_queued_for_one_job_is_queued_for_the_other(
    client, queue
):
    """A message with a summary but no embedding can never be promoted by
    retrieval, and one with an embedding but no summary is never a candidate.
    Both jobs, for every message, from every place a message is written."""
    conversation_id, question = await a_question(client)
    await sse(client, generate_url(conversation_id, question["id"]))

    assert queued(queue, JOB) == queued(queue, EMBED)
    assert len(queued(queue)) >= 2      # the question and the reply


async def test_a_finished_reply_is_queued_for_summarizing(client, queue):
    conversation_id, question = await a_question(client)
    queue.jobs.clear()

    frames = await sse(client, generate_url(conversation_id, question["id"]))

    reply_id = UUID(only(frames, "start")[0]["assistant_message_id"])
    assert queued(queue) == [reply_id]


async def test_a_failed_reply_is_not_queued(client, queue, llm):
    conversation_id, question = await a_question(client)
    queue.jobs.clear()
    llm.fail_after_chunk = 1

    await sse(client, generate_url(conversation_id, question["id"]))

    assert queue.jobs == []


async def test_one_job_failing_to_queue_still_queues_the_other(client, queue):
    """Each job is queued on its own, so a refusal for the first does not
    take the second down with it."""
    await signup(client, ALICE)
    conversation_id = await new_conversation(client)

    original = queue.enqueue_job

    async def refuse_embedding(function, *args, **kwargs):
        if function == EMBED:
            raise ConnectionError("scripted: refused")
        await original(function, *args, **kwargs)

    queue.enqueue_job = refuse_embedding

    response = await post_message(client, conversation_id, role="user", content="hi")

    assert response.status_code == 201
    assert queued(queue) == [UUID(response.json()["message"]["id"])]
    assert queued(queue, EMBED) == []


# --- the worker job -------------------------------------------------------


@pytest.fixture
def worker_on_test_db(monkeypatch, session_factory):
    """The job opens its own sessions from the app's factory, which points at
    the dev database. Point it at the test one instead."""
    monkeypatch.setattr(worker, "async_session_factory", session_factory)


async def test_the_job_writes_the_summary(
    client, session_factory, llm, worker_on_test_db
):
    _, question = await a_question(client)
    message_id = UUID(question["id"])

    written = await worker.summarize_message_job({"llm": llm, "job_try": 1}, message_id)

    assert written is True
    async with session_factory() as other:
        rows = (
            await other.execute(
                select(MessageSummary).where(MessageSummary.message_id == message_id)
            )
        ).scalars().all()
    assert [row.model_used for row in rows] == [settings.summarization_model]


@pytest.mark.parametrize("attempt, wait", [(1, 10), (2, 20)])
async def test_a_summarizer_failure_becomes_a_retry_that_waits_longer_each_time(
    client, llm, worker_on_test_db, attempt, wait
):
    _, question = await a_question(client)
    llm.fail_on_summarize = True

    with pytest.raises(Retry) as raised:
        await worker.summarize_message_job(
            {"llm": llm, "job_try": attempt}, UUID(question["id"])
        )

    assert raised.value.defer_score == wait * 1000


async def test_a_blank_answer_becomes_a_retry_too(
    client, llm, worker_on_test_db, monkeypatch
):
    """A blank answer is retried like any other failure. Marking the job
    failed would leave the message unsummarized until the backfill ran."""
    _, question = await a_question(client)

    async def blank(text, words):
        return ""

    monkeypatch.setattr(llm, "summarize", blank)

    with pytest.raises(Retry):
        await worker.summarize_message_job(
            {"llm": llm, "job_try": 1}, UUID(question["id"])
        )
