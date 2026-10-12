"""Deleting a branch, and the graph staying a tree afterwards.

The failure this guards against is not a crash. A message does not point at
its parent - the edge does - so deleting one message cascades its edges and
leaves its children as messages nothing points at, which is precisely how the
root of a conversation is identified. A conversation with two roots does not
error anywhere: the linear walk picks whichever it finds first and part of the
conversation silently disappears from every view. So these tests count rows
and assert on the shape that is left, not just on status codes.
"""

from uuid import uuid4

from sqlalchemy import func, select

from app.models.edge import Edge
from app.models.generation import Generation
from app.models.message import Message
from app.models.message_embedding import MessageEmbedding
from app.models.message_summary import MessageSummary
from app.services.message import NotABranch, delete_branch

from tests.graph_builders import (
    SPAN,
    link,
    new_conversation,
    new_embedding,
    new_message,
    new_summary,
    new_user,
)

import pytest

ALICE = ("alice@example.com", "a-good-password")
BOB = ("bob@example.com", "another-password")


async def signup(client, who):
    email, password = who
    return await client.post("/auth/signup", json={"email": email, "password": password})


async def login_as(client, who):
    email, password = who
    return await client.post("/auth/login", json={"email": email, "password": password})


async def count(session, model):
    return await session.scalar(select(func.count()).select_from(model))


async def a_thread_with_a_branch(session):
    """A question, its reply, a branch off a span of that reply, and a reply
    inside the branch. The smallest graph where deleting the wrong thing is
    visible."""
    user = await new_user(session)
    conversation = await new_conversation(session, user)

    question = await new_message(session, conversation, content="a question")
    reply = await new_message(
        session,
        conversation,
        role="assistant",
        content="pgvector uses HNSW indexes, which trade recall for speed.",
    )
    await link(session, question, reply)

    branch = await new_message(session, conversation, content="why is that?")
    branch_edge = await link(session, reply, branch, anchor=SPAN)
    branch_reply = await new_message(
        session, conversation, role="assistant", content="because of the graph"
    )
    await link(session, branch, branch_reply)

    conversation.root_message_id = question.id
    await session.commit()

    return {
        "conversation": conversation,
        "question": question,
        "reply": reply,
        "branch": branch,
        "branch_edge": branch_edge,
        "branch_reply": branch_reply,
    }


# --- the service ------------------------------------------------------


async def test_deleting_a_branch_takes_everything_grown_inside_it(session):
    parts = await a_thread_with_a_branch(session)

    removed = await delete_branch(
        session, parts["conversation"], parts["branch"].id
    )

    assert removed == 2
    remaining = await session.execute(select(Message.id))
    assert set(remaining.scalars().all()) == {parts["question"].id, parts["reply"].id}


async def test_the_thread_it_grew_off_is_untouched(session):
    """The reply the branch was anchored in stays, and so does the edge that
    put it on the main path -- only the anchored edge goes."""
    parts = await a_thread_with_a_branch(session)

    await delete_branch(session, parts["conversation"], parts["branch"].id)

    edges = (await session.execute(select(Edge))).scalars().all()
    assert len(edges) == 1
    assert edges[0].child_message_id == parts["reply"].id
    assert edges[0].anchor_start is None


async def test_the_conversation_still_has_exactly_one_root(session):
    """The property that makes this more than a row count. A message nothing
    points at is the root, so an incomplete delete leaves a second one and the
    linear view starts walking from whichever it finds."""
    parts = await a_thread_with_a_branch(session)

    await delete_branch(session, parts["conversation"], parts["branch"].id)

    messages = (await session.execute(select(Message.id))).scalars().all()
    attached = (await session.execute(select(Edge.child_message_id))).scalars().all()
    roots = set(messages) - set(attached)

    assert roots == {parts["question"].id}


async def test_it_goes_all_the_way_down_a_nested_branch(session):
    """A branch inside a branch inside a branch. The walk is recursive, and a
    non-recursive one would leave the deepest one orphaned."""
    parts = await a_thread_with_a_branch(session)
    conversation = parts["conversation"]

    inner = await new_message(session, conversation, content="and why that?")
    await link(session, parts["branch_reply"], inner, anchor=(0, 7))
    inner_reply = await new_message(
        session, conversation, role="assistant", content="because of HNSW"
    )
    await link(session, inner, inner_reply)

    deepest = await new_message(session, conversation, content="deeper still")
    await link(session, inner_reply, deepest, anchor=(0, 7))
    await session.commit()

    removed = await delete_branch(session, conversation, parts["branch"].id)

    assert removed == 5
    assert await count(session, Message) == 2


async def test_a_sibling_branch_off_the_same_span_survives(session):
    """Two branches off one reply are independent threads of thought, and the
    walk must follow edges rather than "everything under this parent"."""
    parts = await a_thread_with_a_branch(session)

    sibling = await new_message(session, parts["conversation"], content="another take")
    await link(session, parts["reply"], sibling, anchor=SPAN)
    await session.commit()

    await delete_branch(session, parts["conversation"], parts["branch"].id)

    remaining = (await session.execute(select(Message.id))).scalars().all()
    assert sibling.id in set(remaining)


async def test_derived_rows_inside_the_branch_go_with_it(session):
    """Generations, summaries and embeddings hang off messages, so the
    database cascade should take them - the same guarantee the conversation
    delete relies on, checked here for a subtree."""
    parts = await a_thread_with_a_branch(session)

    await new_summary(session, parts["branch_reply"])
    await new_embedding(session, parts["branch_reply"])
    session.add(
        Generation(
            user_message_id=parts["branch"].id,
            assistant_message_id=parts["branch_reply"].id,
            strategy_used="SpanOnly",
            model_used="fake-model",
            composed_context="whatever was composed",
        )
    )
    # And one on the main thread, which must survive.
    await new_summary(session, parts["reply"])
    await session.commit()

    await delete_branch(session, parts["conversation"], parts["branch"].id)

    assert await count(session, Generation) == 0
    assert await count(session, MessageEmbedding) == 0
    assert await count(session, MessageSummary) == 1


async def test_the_root_message_is_refused(session):
    """Deleting it would mean deleting the conversation, which has its own
    route -- and it is the one message with no anchored edge above it."""
    parts = await a_thread_with_a_branch(session)

    with pytest.raises(NotABranch):
        await delete_branch(session, parts["conversation"], parts["question"].id)

    assert await count(session, Message) == 4


async def test_a_continuation_is_refused(session):
    """The reply is in the middle of a thread. Deleting it would take the rest
    of that thread with it, which nobody asked for."""
    parts = await a_thread_with_a_branch(session)

    with pytest.raises(NotABranch):
        await delete_branch(session, parts["conversation"], parts["reply"].id)

    assert await count(session, Message) == 4


async def test_a_message_in_another_conversation_is_not_visible(session):
    """The conversation guard, which is inside the walk as well as on the
    lookup -- a foreign message must not even be stepped onto."""
    parts = await a_thread_with_a_branch(session)
    user = await new_user(session, email="second@example.com")
    other = await new_conversation(session, user)
    stranger = await new_message(session, other, content="not yours")
    await session.commit()

    from app.services.message import MessageNotInConversation

    with pytest.raises(MessageNotInConversation):
        await delete_branch(session, parts["conversation"], stranger.id)


# --- the route --------------------------------------------------------


async def branch_off(client, conversation_id, parent_id, anchored_text):
    return await client.post(
        f"/conversations/{conversation_id}/messages",
        json={
            "role": "user",
            "content": "why is that?",
            "parent_message_id": parent_id,
            "anchor_start": 0,
            "anchor_end": len(anchored_text),
            "anchored_text": anchored_text,
        },
    )


async def a_conversation_over_http(client):
    conversation_id = (await client.post("/conversations", json={})).json()["id"]
    question = (
        await client.post(
            f"/conversations/{conversation_id}/messages",
            json={"role": "user", "content": "a question", "parent_message_id": None},
        )
    ).json()["message"]
    reply = (
        await client.post(
            f"/conversations/{conversation_id}/messages",
            json={
                "role": "assistant",
                "content": "a reply worth branching from",
                "parent_message_id": question["id"],
            },
        )
    ).json()["message"]
    return conversation_id, question, reply


async def test_delete_returns_204_and_the_graph_loses_the_branch(client):
    await signup(client, ALICE)
    conversation_id, question, reply = await a_conversation_over_http(client)
    branch = (await branch_off(client, conversation_id, reply["id"], "a reply")).json()

    response = await client.delete(
        f"/conversations/{conversation_id}/messages/{branch['message']['id']}"
    )
    assert response.status_code == 204

    graph = (await client.get(f"/conversations/{conversation_id}/messages")).json()
    assert [m["id"] for m in graph["messages"]] == [question["id"], reply["id"]]
    assert len(graph["edges"]) == 1


async def test_deleting_a_continuation_over_http_is_422(client):
    await signup(client, ALICE)
    conversation_id, _question, reply = await a_conversation_over_http(client)

    response = await client.delete(
        f"/conversations/{conversation_id}/messages/{reply['id']}"
    )
    assert response.status_code == 422
    assert "branch" in response.json()["detail"].lower()


async def test_deleting_an_unknown_message_is_404(client):
    await signup(client, ALICE)
    conversation_id, _question, _reply = await a_conversation_over_http(client)

    response = await client.delete(
        f"/conversations/{conversation_id}/messages/{uuid4()}"
    )
    assert response.status_code == 404


async def test_someone_elses_branch_is_404_and_survives(client):
    await signup(client, ALICE)
    conversation_id, _question, reply = await a_conversation_over_http(client)
    branch = (await branch_off(client, conversation_id, reply["id"], "a reply")).json()
    branch_id = branch["message"]["id"]

    await signup(client, BOB)
    # 404 from the ownership dependency, before the handler body runs.
    assert (
        await client.delete(f"/conversations/{conversation_id}/messages/{branch_id}")
    ).status_code == 404

    await login_as(client, ALICE)
    graph = (await client.get(f"/conversations/{conversation_id}/messages")).json()
    assert branch_id in {m["id"] for m in graph["messages"]}


async def test_delete_requires_a_session(client):
    assert (
        await client.delete(f"/conversations/{uuid4()}/messages/{uuid4()}")
    ).status_code == 401
