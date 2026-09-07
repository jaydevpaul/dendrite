"""Builders for graph shapes, used by the B2 service-level tests.

Deliberately not going through the API. B1's routes are already tested; what
these tests need is arbitrary graph *shapes*, including ones the API refuses to
build - a cross-conversation edge, or a strategy override on a continuation.

The small builders flush but do not commit, so a test can assemble a shape and
commit it once at the end. The two whole-thread builders at the bottom commit
for themselves, because what they build is a starting point rather than a piece.
"""

from app.core.config import settings
from app.llm.fake import fake_vector
from app.models.conversation import Conversation
from app.models.edge import Edge
from app.models.message import Message
from app.models.message_embedding import MessageEmbedding
from app.models.message_summary import MessageSummary
from app.models.user import User

# The assistant text a branch anchors into, with the offsets of the phrase
# "trade recall for speed" computed rather than written by hand.
PARENT_TEXT = "pgvector uses HNSW indexes, which trade recall for speed."
ANCHOR_TEXT = "trade recall for speed"
ANCHOR_START = PARENT_TEXT.index(ANCHOR_TEXT)
ANCHOR_END = ANCHOR_START + len(ANCHOR_TEXT)
SPAN = (ANCHOR_START, ANCHOR_END)


async def new_user(session, email="walker@example.com"):
    user = User(email=email, password_hash="not-a-real-hash")
    session.add(user)
    await session.flush()
    return user


async def new_conversation(session, user, default_strategy="HierarchicalDecay"):
    conversation = Conversation(user_id=user.id, default_strategy=default_strategy)
    session.add(conversation)
    await session.flush()
    return conversation


async def new_message(session, conversation, role="user", content="a message"):
    message = Message(conversation_id=conversation.id, role=role, content=content)
    session.add(message)
    await session.flush()
    return message


async def link(session, parent, child, anchor=None, override=None):
    """Attach child under parent.

    `anchor` as an (start, end) pair makes it a branch and derives
    anchored_text from the parent's real content, so the edge cannot drift out
    of agreement with itself. None makes it a continuation.
    """
    edge = Edge(parent_message_id=parent.id, child_message_id=child.id)

    if anchor is not None:
        start, end = anchor
        edge.anchor_start = start
        edge.anchor_end = end
        edge.anchored_text = parent.content[start:end]

    edge.strategy_override = override

    session.add(edge)
    await session.flush()
    return edge


async def chain_of(session, conversation, length):
    """A straight line of continuations, oldest first. Returns every message."""
    messages = [await new_message(session, conversation, content="m0")]

    for i in range(1, length):
        role = "assistant" if i % 2 else "user"
        child = await new_message(session, conversation, role, f"m{i}")
        await link(session, messages[-1], child)
        messages.append(child)

    return messages


async def new_summary(
    session,
    message,
    summary_text="a shorter version of it",
    model_used="fake-summariser",
    created_at=None,
):
    """A derived summary hanging off a message.

    `created_at` is normally left to the database, which fills it with the
    transaction's clock - so several summaries written by one test all carry
    the same timestamp. Pass it explicitly when a test needs one summary to be
    genuinely older than another.
    """
    summary = MessageSummary(
        message_id=message.id,
        summary_text=summary_text,
        model_used=model_used,
    )

    if created_at is not None:
        summary.created_at = created_at

    session.add(summary)
    await session.flush()
    return summary


async def new_embedding(
    session,
    message,
    text=None,
    model_used=None,
    created_at=None,
):
    """A vector hanging off a message.

    The vector is derived from `text`, which defaults to the message's own
    content - what a real embedder would have been handed. Pass `text`
    explicitly when a test needs to control exactly how close two candidates
    are to the query, rather than relying on the fixture's prose.

    `model_used` defaults to the configured embedding model, so a row written
    here is one the strategy's own model filter will find. Pass something else
    to build a row from a different vector space, which retrieval must ignore.

    `created_at` is normally left to the database. Pass it when a test needs
    one row to be genuinely older than another.
    """
    embedding = MessageEmbedding(
        message_id=message.id,
        embedding=fake_vector(message.content if text is None else text),
        model_used=settings.embedding_model if model_used is None else model_used,
    )

    if created_at is not None:
        embedding.created_at = created_at

    session.add(embedding)
    await session.flush()
    return embedding


# The question a branch is opened to ask, and the text the anchor points into.
QUESTION_TEXT = "What does that cost me?"


async def a_question(
    session,
    default_strategy="ParentOnly",
    anchor=SPAN,
    override=None,
    trunk_length=3,
):
    """A trunk of continuations, an assistant reply, then the user question.

    The reply carries the text the anchor offsets point into, so the last link
    is a real branch. `anchor=None` makes it a continuation instead, which is
    the single thing that changes what resolution answers.

    Returns the conversation, the question, and the ancestors oldest-first.
    """
    user = await new_user(session)
    conversation = await new_conversation(
        session, user, default_strategy=default_strategy
    )
    trunk = await chain_of(session, conversation, trunk_length)

    reply = await new_message(session, conversation, "assistant", PARENT_TEXT)
    await link(session, trunk[-1], reply)

    question = await new_message(session, conversation, "user", QUESTION_TEXT)
    await link(session, reply, question, anchor=anchor, override=override)

    await session.commit()
    return conversation, question, [*trunk, reply]


async def a_deep_question(session, default_strategy, anchor=None, summarised="older"):
    """Seven ancestors, deep enough that the three-level tier bites.

    "older" summarizes the four the default tier would send short, which is the
    ordinary state. "all" gives every level a summary, so a test that shortens
    the tier sees more summaries rather than more full text sent for want of a
    row to use.
    """
    conversation, question, ancestors = await a_question(
        session,
        default_strategy=default_strategy,
        anchor=anchor,
        trunk_length=6,
    )

    for ancestor in {"older": ancestors[:-3], "all": ancestors}[summarised]:
        await new_summary(
            session, ancestor, summary_text=f"a summary of {ancestor.content}"
        )

    await session.commit()
    return conversation, question, ancestors
