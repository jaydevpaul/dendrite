"""The streaming generate route, its four events, and the pending flag.

Every test here parses the wire format rather than inspecting objects, because
the wire format is the part that can break silently. A frame boundary is a
blank line and a data line is JSON, so a reply containing newlines is the case
that matters most - and it is the one that would present as the model writing
broken markdown rather than as a transport bug.
"""

import json
from uuid import UUID

from app.llm.fake import DEFAULT_CHUNKS
from app.models.message_summary import MessageSummary
from app.schemas.message import MessageOut
from tests.test_message_routes import (
    ALICE,
    BOB,
    login_as,
    new_conversation,
    post_message,
    signup,
)

MULTILINE_CHUNKS = ["Two things:\n\n1. one\n", "2. two\n\nThat is all."]


# --- reading the stream ---------------------------------------------------


async def sse(client, url):
    """Every frame of an event stream, as (event, data) pairs.

    Split on the blank line that terminates a frame, so a frame carrying a raw
    newline would come back here as two malformed frames rather than as text
    that merely looks wrong.
    """
    frames = []

    async with client.stream("POST", url) as response:
        assert response.status_code == 200, await response.aread()
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join([chunk async for chunk in response.aiter_text()])

    for block in body.split("\n\n"):
        if not block.strip():
            continue
        name, data = block.split("\n", 1)
        frames.append(
            (name.removeprefix("event: "), json.loads(data.removeprefix("data: ")))
        )

    return frames


def only(frames, event):
    return [data for name, data in frames if name == event]


async def a_question(client, who=ALICE, **conversation):
    """A signed-up user with a conversation and one question in it."""
    await signup(client, who)
    conversation_id = await new_conversation(client, **conversation)

    question = (
        await post_message(
            client, conversation_id, role="user", content="What does that cost me?"
        )
    ).json()["message"]

    return conversation_id, question


async def a_deep_question(client, **conversation):
    """A question with seven turns above it, all of them unsummarized.

    Deep enough that the three-level tier starts asking for summaries, which
    is what the two decay arms need before they can behave differently from
    full inheritance.
    """
    conversation_id, parent = await a_question(client, **conversation)

    for index in range(6):
        parent = (
            await post_message(
                client,
                conversation_id,
                role="assistant" if index % 2 == 0 else "user",
                content=f"turn {index}",
                parent_message_id=parent["id"],
            )
        ).json()["message"]

    question = (
        await post_message(
            client,
            conversation_id,
            role="user",
            content="so what does it cost?",
            parent_message_id=parent["id"],
        )
    ).json()["message"]

    return conversation_id, question


async def summarise_everything(client, session, conversation_id):
    """Give every message in the conversation a summary row.

    Nothing writes summaries yet - that is a background job in a later layer -
    so a test that needs the retrieval arm to have candidates to rank has to
    put them there itself. Which levels actually get sent short is still the
    tier's decision, not this function's.
    """
    graph = (await client.get(f"/conversations/{conversation_id}/messages")).json()

    for message in graph["messages"]:
        session.add(
            MessageSummary(
                message_id=UUID(message["id"]),
                summary_text=f"a summary of {message['content']}",
                model_used="fake-summariser",
            )
        )

    await session.commit()


def generate_url(conversation_id, message_id):
    return f"/conversations/{conversation_id}/messages/{message_id}/generate"


# --- the four events ------------------------------------------------------


async def test_the_stream_opens_by_naming_the_row_and_the_strategy(client):
    """The client needs the assistant message id before any text arrives - it
    has nowhere to put the chunks otherwise - and the strategy plus where it
    came from is what answers "why did this reply get this context"."""
    conversation_id, question = await a_question(client)

    frames = await sse(client, generate_url(conversation_id, question["id"]))

    (start,) = only(frames, "start")
    assert start["assistant_message_id"]
    assert start["strategy"] == "HierarchicalDecayWithRetrieval"
    assert start["source"] == "conversation_default"
    assert start["model"]


async def test_every_chunk_arrives_as_its_own_event(client):
    conversation_id, question = await a_question(client)

    frames = await sse(client, generate_url(conversation_id, question["id"]))

    assert [chunk["text"] for chunk in only(frames, "chunk")] == list(DEFAULT_CHUNKS)


async def test_a_reply_full_of_newlines_survives_the_wire(client, llm):
    """The frame boundary is a blank line, so a raw newline in a data line ends
    the frame early and the rest of the chunk is read as a new one. Encoding
    the text as JSON is what stops that, and this is what proves it."""
    llm.chunks = MULTILINE_CHUNKS
    conversation_id, question = await a_question(client)

    frames = await sse(client, generate_url(conversation_id, question["id"]))

    chunks = only(frames, "chunk")
    assert [chunk["text"] for chunk in chunks] == MULTILINE_CHUNKS
    # One frame per chunk, not one per line.
    assert len(chunks) == len(MULTILINE_CHUNKS)
    assert len(only(frames, "done")) == 1


async def test_the_stream_finishes_with_the_record_and_its_tokens(client):
    conversation_id, question = await a_question(client)

    frames = await sse(client, generate_url(conversation_id, question["id"]))

    assert frames[-1][0] == "done"
    done = frames[-1][1]
    assert done["generation_id"]
    assert done["input_tokens"] > 0
    assert done["output_tokens"] > 0
    assert done["degradations"] == []


async def test_the_done_event_carries_the_degradations(client):
    """Not stored anywhere - the strategy column records what ran, and this
    list is how the run itself says what was missing while it ran. Here the
    summariser has not caught up, so the older levels went out in full."""
    conversation_id, question = await a_deep_question(
        client, default_strategy="HierarchicalDecay"
    )

    frames = await sse(client, generate_url(conversation_id, question["id"]))

    assert only(frames, "done")[0]["degradations"] == ["summary_missing"]


async def test_the_start_event_names_the_arm_that_actually_ran(client, session, llm):
    """Retrieval was resolved and the embedder refused, so plain decay is what
    composed the prompt - and that is what the stream announces, because it is
    also what the stored record will say. A client told otherwise would be
    displaying something the database contradicts.

    The summaries matter: with nothing summarized there is nothing for
    retrieval to rank, so it never calls the embedder and there is no fallback
    to observe."""
    conversation_id, question = await a_deep_question(
        client, default_strategy="HierarchicalDecayWithRetrieval"
    )
    await summarise_everything(client, session, conversation_id)
    llm.fail_on_embed = True

    frames = await sse(client, generate_url(conversation_id, question["id"]))

    (start,) = only(frames, "start")
    assert start["strategy"] == "HierarchicalDecay"
    assert start["source"] == "conversation_default"


async def test_an_undegraded_retrieval_run_reports_itself(client, session, llm):
    """The other half of the comparison: with the embedder answering, the arm
    that ran is the arm that was resolved. Without this a stream that always
    announced the simpler arm would pass the test above."""
    conversation_id, question = await a_deep_question(
        client, default_strategy="HierarchicalDecayWithRetrieval"
    )
    await summarise_everything(client, session, conversation_id)

    frames = await sse(client, generate_url(conversation_id, question["id"]))

    assert only(frames, "start")[0]["strategy"] == "HierarchicalDecayWithRetrieval"


async def test_a_failure_part_way_through_arrives_as_an_error_event(client, llm):
    """The response opened with a 200 long before this, so the failure cannot
    be a status code any more. The detail is deliberately not the provider's
    own message."""
    llm.fail_after_chunk = 1
    conversation_id, question = await a_question(client)

    frames = await sse(client, generate_url(conversation_id, question["id"]))

    assert [name for name, _ in frames] == ["start", "chunk", "error"]
    assert "scripted" not in only(frames, "error")[0]["detail"]


# --- what the graph shows afterwards --------------------------------------


async def test_the_reply_is_in_the_graph_when_the_stream_ends(client):
    conversation_id, question = await a_question(client)

    frames = await sse(client, generate_url(conversation_id, question["id"]))
    assistant_id = only(frames, "start")[0]["assistant_message_id"]

    graph = (await client.get(f"/conversations/{conversation_id}/messages")).json()
    reply = next(m for m in graph["messages"] if m["id"] == assistant_id)

    assert reply["content"] == "".join(DEFAULT_CHUNKS)
    assert reply["pending"] is False
    assert reply["updated_at"] == reply["created_at"]

    (edge,) = [e for e in graph["edges"] if e["child_message_id"] == assistant_id]
    assert edge["parent_message_id"] == question["id"]


async def test_a_failed_reply_stays_in_the_graph_and_stays_pending(client, llm):
    """Nothing is deleted, so the question keeps its retry affordance and the
    composed context survives as the only record of what was attempted."""
    llm.fail_after_chunk = 0
    conversation_id, question = await a_question(client)

    frames = await sse(client, generate_url(conversation_id, question["id"]))
    assistant_id = only(frames, "start")[0]["assistant_message_id"]

    graph = (await client.get(f"/conversations/{conversation_id}/messages")).json()
    reply = next(m for m in graph["messages"] if m["id"] == assistant_id)

    assert reply["content"] == ""
    assert reply["pending"] is True


# --- pending, on its own --------------------------------------------------


def _out(role, content):
    from datetime import UTC, datetime
    from uuid import uuid4

    now = datetime.now(UTC)
    return MessageOut(
        id=uuid4(),
        conversation_id=uuid4(),
        role=role,
        content=content,
        created_at=now,
        updated_at=now,
    )


def test_a_blank_assistant_message_reads_as_pending():
    """Derived, not stored. The API refuses empty content, so the only thing in
    the system that can produce a blank assistant row is the generate route's
    own insert - which means blankness already says a generation happened."""
    assert _out(role="assistant", content="").pending is True


def test_a_reply_with_text_is_not_pending():
    assert _out(role="assistant", content="here you go").pending is False


def test_a_user_message_is_never_pending():
    """Only generation writes blank rows, and it only ever writes assistant
    ones. A blank user message would be a different problem entirely."""
    assert _out(role="user", content="").pending is False


# --- who may generate -----------------------------------------------------


async def test_generating_a_reply_to_a_reply_is_refused(client):
    """A reply to a reply is how the blank-row mistake is made: the walk would
    start one level too low and every branch would compose as the conversation
    default instead of its span."""
    conversation_id, question = await a_question(client)

    frames = await sse(client, generate_url(conversation_id, question["id"]))
    assistant_id = only(frames, "start")[0]["assistant_message_id"]

    response = await client.post(generate_url(conversation_id, assistant_id))
    assert response.status_code == 422


async def test_generating_for_an_unknown_message_is_not_found(client):
    from uuid import uuid4

    conversation_id, _ = await a_question(client)

    response = await client.post(generate_url(conversation_id, uuid4()))
    assert response.status_code == 404


async def test_generating_in_someone_elses_conversation_is_not_found(client):
    """404 rather than 403 - a 403 confirms the conversation exists, which is
    the fact the probe is after."""
    conversation_id, question = await a_question(client, ALICE)
    await signup(client, BOB)
    await login_as(client, BOB)

    response = await client.post(generate_url(conversation_id, question["id"]))
    assert response.status_code == 404


async def test_generating_without_a_session_is_rejected(client):
    conversation_id, question = await a_question(client)
    await client.post("/auth/logout")

    response = await client.post(generate_url(conversation_id, question["id"]))
    assert response.status_code == 401

