"""Builders for graph shapes, used by the B2 service-level tests.

Deliberately not going through the API. B1's routes are already tested; what
these tests need is arbitrary graph *shapes*, including ones the API refuses to
build - a cross-conversation edge, or a strategy override on a continuation.

Every builder flushes but does not commit, so a test can assemble a shape and
commit it once at the end.
"""

from app.models.conversation import Conversation
from app.models.edge import Edge
from app.models.message import Message
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
