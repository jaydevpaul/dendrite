"""Queueing embedding jobs from the routes, and the worker job that runs them.

The routes are tested against a recording queue rather than Redis: what matters
is which message ids were handed over and when, and that a queue which cannot be
reached never turns a saved message into a failed request. The worker job is
called directly, without arq around it, because what is worth testing there is
its own small decision - an embedder failure becomes a retry, not a dead job.
"""

from uuid import UUID

import pytest
from arq import Retry
from sqlalchemy import select

from app import worker
from app.models.message import Message
from app.models.message_embedding import MessageEmbedding
from tests.test_generate_route import a_question, only, sse
from tests.test_message_routes import ALICE, new_conversation, post_message, signup

JOB = "embed_message_job"


def queued(queue, job=JOB):
    """The message ids queued under one job name. Every saved message also
    queues a summary job, which this file is not about."""
    return [message_id for name, message_id in queue.jobs if name == job]


def generate_url(conversation_id, message_id):
    return f"/conversations/{conversation_id}/messages/{message_id}/generate"


# --- the name the routes queue under --------------------------------------


def test_the_queued_name_is_a_function_the_worker_runs():
    """arq finds the job by this string. A rename on one side only would queue
    jobs no worker ever picks up, and nothing anywhere would raise."""
    assert JOB in {function.__name__ for function in worker.WorkerSettings.functions}


# --- writing a message ----------------------------------------------------


async def test_a_saved_message_is_queued_for_embedding(client, queue):
    await signup(client, ALICE)
    conversation_id = await new_conversation(client)

    response = await post_message(client, conversation_id, role="user", content="hi")

    assert response.status_code == 201
    message_id = UUID(response.json()["message"]["id"])
    assert queued(queue) == [message_id]


async def test_a_rejected_message_queues_nothing(client, queue):
    await signup(client, ALICE)
    conversation_id = await new_conversation(client)
    await post_message(client, conversation_id, role="user", content="the root")
    queue.jobs.clear()

    # A second parentless message is a second root, which is refused.
    response = await post_message(client, conversation_id, role="user", content="again")

    assert response.status_code == 409
    assert queue.jobs == []


async def test_a_message_is_still_saved_when_the_queue_is_down(client, queue, session):
    """The row is committed before the enqueue is tried, so a failure there has
    to stay out of the response. A 500 would tell the reader their message was
    lost when it was not."""
    await signup(client, ALICE)
    conversation_id = await new_conversation(client)
    queue.down = True

    response = await post_message(client, conversation_id, role="user", content="hi")

    assert response.status_code == 201
    message_id = UUID(response.json()["message"]["id"])
    assert await session.get(Message, message_id) is not None


# --- generating a reply ---------------------------------------------------


async def test_a_finished_reply_is_queued_for_embedding(client, queue):
    conversation_id, question = await a_question(client)
    queue.jobs.clear()

    frames = await sse(client, generate_url(conversation_id, question["id"]))

    reply_id = UUID(only(frames, "start")[0]["assistant_message_id"])
    assert queued(queue) == [reply_id]


async def test_a_failed_reply_is_not_queued(client, queue, llm):
    """A failed run leaves the reply blank. The job would skip it anyway, but
    queueing it would be work done to find that out."""
    conversation_id, question = await a_question(client)
    queue.jobs.clear()
    llm.fail_after_chunk = 1

    frames = await sse(client, generate_url(conversation_id, question["id"]))

    assert only(frames, "error")
    assert queue.jobs == []


async def test_a_reply_still_finishes_when_the_queue_is_down(client, queue):
    conversation_id, question = await a_question(client)
    queue.down = True

    frames = await sse(client, generate_url(conversation_id, question["id"]))

    assert only(frames, "done")
    assert not only(frames, "error")


# --- the worker job -------------------------------------------------------


@pytest.fixture
def worker_on_test_db(monkeypatch, session_factory):
    """The job opens its own sessions from the app's factory, which points at
    the dev database. Point it at the test one instead."""
    monkeypatch.setattr(worker, "async_session_factory", session_factory)


async def test_the_job_writes_the_embedding(
    client, session_factory, llm, worker_on_test_db
):
    conversation_id, question = await a_question(client)
    message_id = UUID(question["id"])

    written = await worker.embed_message_job({"llm": llm, "job_try": 1}, message_id)

    assert written is True
    async with session_factory() as other:
        rows = (
            await other.execute(
                select(MessageEmbedding).where(MessageEmbedding.message_id == message_id)
            )
        ).scalars().all()
    assert len(rows) == 1


@pytest.mark.parametrize("attempt, wait", [(1, 10), (2, 20)])
async def test_an_embedder_failure_becomes_a_retry_that_waits_longer_each_time(
    client, llm, worker_on_test_db, attempt, wait
):
    """arq retries a job only when it raises Retry. Any other exception marks
    it failed for good, so a provider's bad minute would cost the message its
    vector until someone ran the backfill."""
    conversation_id, question = await a_question(client)
    llm.fail_on_embed = True

    with pytest.raises(Retry) as raised:
        await worker.embed_message_job(
            {"llm": llm, "job_try": attempt}, UUID(question["id"])
        )

    assert raised.value.defer_score == wait * 1000
