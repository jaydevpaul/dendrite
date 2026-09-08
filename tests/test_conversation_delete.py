"""Deleting a conversation: the route's ownership scoping, and the cascade.

The cascade is a database behaviour, not application code, so the only way to
know it is really configured is to write the rows and count them afterwards.
A migration that missed one foreign key leaves orphans that nothing in the app
would ever notice - and the ORM issues the same single DELETE either way.
"""

from uuid import uuid4

from sqlalchemy import func, select

from app.models.conversation import Conversation
from app.models.edge import Edge
from app.models.generation import Generation
from app.models.message import Message
from app.models.message_embedding import MessageEmbedding
from app.models.message_summary import MessageSummary
from app.services.conversation import delete_conversation

from tests.graph_builders import (
    SPAN,
    link,
    new_conversation,
    new_embedding,
    new_message,
    new_summary,
    new_user,
)

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


# --- the route --------------------------------------------------------


async def test_delete_returns_204_and_the_conversation_is_gone(client):
    await signup(client, ALICE)
    conversation_id = (await client.post("/conversations", json={})).json()["id"]

    response = await client.delete(f"/conversations/{conversation_id}")
    assert response.status_code == 204

    assert (await client.get(f"/conversations/{conversation_id}")).status_code == 404
    assert (await client.get("/conversations")).json() == []


async def test_deleting_someone_elses_conversation_is_a_404_and_leaves_it_alone(client):
    await signup(client, ALICE)
    conversation_id = (await client.post("/conversations", json={})).json()["id"]

    await signup(client, BOB)
    # 404 rather than 403: a 403 would confirm the id exists.
    assert (await client.delete(f"/conversations/{conversation_id}")).status_code == 404

    await login_as(client, ALICE)
    assert (await client.get(f"/conversations/{conversation_id}")).status_code == 200


async def test_deleting_an_unknown_id_is_a_404(client):
    await signup(client, ALICE)

    assert (await client.delete(f"/conversations/{uuid4()}")).status_code == 404


async def test_delete_requires_a_session(client):
    assert (await client.delete(f"/conversations/{uuid4()}")).status_code == 401


async def test_delete_leaves_the_users_other_conversations(client):
    await signup(client, ALICE)
    doomed = (await client.post("/conversations", json={"title": "doomed"})).json()["id"]
    kept = (await client.post("/conversations", json={"title": "kept"})).json()["id"]

    await client.delete(f"/conversations/{doomed}")

    titles = [row["title"] for row in (await client.get("/conversations")).json()]
    assert titles == ["kept"]
    assert (await client.get(f"/conversations/{kept}")).status_code == 200


# --- the cascade ------------------------------------------------------


async def test_delete_takes_every_branch_and_all_derived_rows(session):
    """One DELETE has to remove the messages, the edges - continuation *and*
    anchored - the generations, the summaries and the embeddings. A branch is
    just a message in the same conversation, so nothing about it is special
    here; the test builds one to prove exactly that.
    """
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

    # A branch off a highlighted span of the reply, with its own reply under it.
    branch = await new_message(session, conversation, content="why is that?")
    await link(session, reply, branch, anchor=SPAN)
    branch_reply = await new_message(
        session, conversation, role="assistant", content="because of the graph"
    )
    await link(session, branch, branch_reply)

    # Derived rows, which is what an incomplete cascade orphans.
    await new_summary(session, reply)
    await new_embedding(session, reply)
    for user_message, assistant_message in ((question, reply), (branch, branch_reply)):
        session.add(
            Generation(
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
                strategy_used="SpanOnly",
                model_used="fake-model",
                composed_context="whatever was composed",
            )
        )

    conversation.root_message_id = question.id
    await session.commit()

    assert await count(session, Message) == 4
    assert await count(session, Edge) == 3
    assert await count(session, Generation) == 2

    await delete_conversation(session, conversation)

    for model in (
        Conversation,
        Message,
        Edge,
        Generation,
        MessageSummary,
        MessageEmbedding,
    ):
        assert await count(session, model) == 0, model.__tablename__


async def test_delete_leaves_another_conversations_rows_untouched(session):
    """The cascade follows message.conversation_id, so a second conversation's
    messages have to survive - the guard against a cascade written from the
    user instead of the conversation."""
    user = await new_user(session)
    doomed = await new_conversation(session, user)
    kept = await new_conversation(session, user)

    await new_message(session, doomed, content="in the doomed one")
    survivor = await new_message(session, kept, content="in the kept one")
    await new_summary(session, survivor)
    await session.commit()

    await delete_conversation(session, doomed)

    assert await count(session, Message) == 1
    assert await count(session, MessageSummary) == 1
    assert await count(session, Conversation) == 1
