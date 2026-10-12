from uuid import UUID

from app.models.conversation import Conversation
from app.models.message import Message
from app.models.edge import Edge
from app.schemas.message import MessageCreate


from sqlalchemy import delete, func, literal, select, update
from sqlalchemy.ext.asyncio import AsyncSession

class ParentNotFound(Exception):
    """parent_message_id is not a message in this conversation.

    Like ConversationNotFound, it deliberately does not distinguish "no such
    message" from "someone else's message" - the route turns both into a 404."""

class RootAlreadyExists(Exception):
    """A parentless message arrived at a conversation that already has a root."""

class InvalidAnchor(Exception):
    """The anchor does not line up with the parent message's text."""


async def get_message_in_conversation(
        session:AsyncSession,
        conversation: Conversation,
        message_id:UUID,
):
    """The message with this id - but only if it lives in this conversation."""

    result = await session.execute(

        select(Message).where(
            Message.id==message_id,
            Message.conversation_id==conversation.id,
        )
    )

    return result.scalar_one_or_none()

async def _load_parent(
        session:AsyncSession,
        conversation:Conversation,
        parent_message_id:UUID
):
    
    parent =await get_message_in_conversation(session,conversation,parent_message_id)

    if parent is None:
        raise ParentNotFound(parent_message_id)

    return parent

def _check_anchor(parent:Message,data:MessageCreate):

    """Compare the anchor against the text it claims to point at"""

    if data.anchor_start is None:
        return

    if data.anchor_end > len(parent.content):
        raise InvalidAnchor(
            f"anchor_end {data.anchor_end} is past the end of the parent message, "
            f"which is {len(parent.content)} characters long"
        )


    if parent.content[data.anchor_start : data.anchor_end] != data.anchored_text:
        raise InvalidAnchor(
            "anchored_text does not match the parent message at that offset"
        )

async def _claim_root(
        session: AsyncSession,
        conversation:Conversation,
        message_id: UUID
):
    result= await session.execute(
        update(Conversation)
        .where(
            Conversation.id==conversation.id,
            Conversation.root_message_id.is_(None)
        )
        .values(root_message_id=message_id)
        .execution_options(synchronize_session=False)
    )

    if result.rowcount == 0:
        # Read the id BEFORE rolling back. rollback() expires every object in
        # the session, so conversation.id afterwards would need a fresh SELECT -
        # and this is an exception path, where SQLAlchemy's async machinery is
        # not set up to run one (MissingGreenlet).
        conversation_id = conversation.id
        await session.rollback()
        raise RootAlreadyExists(conversation_id)

    # That UPDATE went straight to the database, so this session's Conversation
    # object still believes root_message_id is None. Expire it, and the next
    # read fetches the row again instead of trusting the stale copy.
    session.expire(conversation)

async def create_message(
        session: AsyncSession,
        conversation: Conversation,
        data: MessageCreate,
):
    parent = None
    if data.parent_message_id is not None:
        parent = await _load_parent(session,conversation,data.parent_message_id)
 
        #   raises error if any problem in anchor mismatch  
        _check_anchor(parent,data) 

    message = Message(
        conversation_id=conversation.id,
        role=data.role,
        content=data.content,
    )

    session.add(message)
    # flush sends the INSERT without committing, so message.id exists for the
    # edge to point at - and everything still rolls back as one unit.
    await session.flush()

    edge=None

    if parent is not None:
        edge = Edge(
            parent_message_id=parent.id,
            child_message_id=message.id,
            anchor_start =data.anchor_start,
            anchor_end=data.anchor_end,
            anchored_text=data.anchored_text,
            strategy_override=data.strategy_override,
        )
        session.add(edge)

        conversation.updated_at = func.now()
    else:
        await _claim_root(session,conversation,message.id)

    await session.commit()

    return message, edge
    
async def list_conversation_graph(
        session: AsyncSession,
        conversation: Conversation,
):
    result = await session.execute(
    select(Message)
    .where(Message.conversation_id == conversation.id)
    .order_by(Message.created_at, Message.id)
    )

    messages = result.scalars().all()

    if not messages:
        return [],[]

    result = await session.execute(
        select(Edge)
        .where(Edge.child_message_id.in_([m.id for m in messages]))
        .order_by(Edge.created_at, Edge.id)
    )

    edges=result.scalars().all()

    return list(messages), list(edges)


# A runaway guard, not a working depth. The mirror of the ancestor walk's cap
# and there for the same reason: edge topology should make a cycle
# unconstructible, and this is what stops the query if a future write path
# ever manages one.
SUBTREE_SAFETY_CAP = 200


class MessageNotInConversation(Exception):
    """No message with that id is visible in this conversation.

    Does not distinguish "no such message" from "someone else's message", for
    the same reason ConversationNotFound does not - the route answers 404 to
    both, and a 403 would confirm the id exists."""


class NotABranch(Exception):
    """This message is not the first message of a branch.

    Deleting a message takes everything under it, so the only message that can
    be deleted is one whose whole subtree is a thing a reader chose to start:
    a branch. Deleting a message in the middle of a thread would silently take
    the rest of that thread with it, and deleting the root would be deleting
    the conversation, which has its own route."""


async def _attaching_edge(session: AsyncSession, message_id: UUID):
    """The edge that points down at this message. None for the root."""

    result = await session.execute(
        select(Edge).where(Edge.child_message_id == message_id)
    )
    return result.scalar_one_or_none()


async def _descendant_ids(
        session: AsyncSession,
        conversation: Conversation,
        message_id: UUID,
) -> list[UUID]:
    """Every message below this one, however it was attached.

    This walk goes *down*, so it joins on parent_message_id - the exact
    opposite of the ancestor walk, where doing that is the bug. Down the tree
    the fan-out is the point: a message may have several children, and all of
    them are going.

    Both the seed and the recursive step filter on conversation_id, inside the
    CTE. Filtering after the walk would be too late - by then it has already
    stepped through a foreign message into whatever hangs below it.
    """

    seed = (
        select(
            Edge.child_message_id.label("message_id"),
            literal(1).label("depth"),
        )
        .join(Message, Message.id == Edge.child_message_id)
        .where(
            Edge.parent_message_id == message_id,
            Message.conversation_id == conversation.id,
        )
    )

    walk = seed.cte("descendant_walk", recursive=True)

    step = (
        select(Edge.child_message_id, walk.c.depth + literal(1))
        .select_from(walk)
        .join(Edge, Edge.parent_message_id == walk.c.message_id)
        .join(Message, Message.id == Edge.child_message_id)
        .where(
            walk.c.depth < SUBTREE_SAFETY_CAP,
            Message.conversation_id == conversation.id,
        )
    )

    walk = walk.union_all(step)

    result = await session.execute(select(walk.c.message_id).select_from(walk))
    return list(result.scalars().all())


async def delete_branch(
        session: AsyncSession,
        conversation: Conversation,
        message_id: UUID,
) -> int:
    """Delete a branch and everything grown inside it. Returns the row count.

    The messages are deleted explicitly rather than by cascade, because a
    message does not point at its parent - the edge does. So deleting one
    message takes its edges with it and leaves its children as messages
    nothing points at, and a message nothing points at is exactly how the root
    of a conversation is identified. The result would be a conversation with
    several roots and a thread that walks whichever one it finds first.
    """

    message = await get_message_in_conversation(session, conversation, message_id)

    if message is None:
        raise MessageNotInConversation(message_id)

    edge = await _attaching_edge(session, message_id)

    if edge is None:
        raise NotABranch("the conversation's root message")

    if edge.anchor_start is None:
        raise NotABranch("a continuation, not a branch")

    doomed = [message_id, *await _descendant_ids(session, conversation, message_id)]

    await session.execute(
        delete(Message).where(
            Message.id.in_(doomed),
            # Belt and braces: the walk is already conversation-scoped, and
            # this makes a bug there a no-op rather than a cross-conversation
            # delete.
            Message.conversation_id == conversation.id,
        )
    )
    await session.commit()

    return len(doomed)
