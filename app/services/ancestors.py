from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import literal,select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.edge import Edge
from app.models.message import Message
from app.services.message import get_message_in_conversation


# A runaway guard, not a working setting (section 8.13). Edge topology is
# immutable and child_message_id is UNIQUE, so a cycle is not constructible
# today - but two edges (child=B parent=A) and (child=A parent=B) both satisfy
# that constraint, so one is not *impossible*. This is what stops the loop if
# a future write path ever creates one.
WALK_SAFETY_CAP = 200

class MessageNotFound(Exception):
    """The starting message is not a message in this conversation."""



@dataclass(frozen=True)
class AncestorStep:
    """"One level of the chain.

    `edge` is the edge attaching the level *below* this one, not the one above
    it. At depth 1 that is the edge attaching the starting message - the edge
    holding the anchor, which is the whole input to SpanOnly and to the "span
    full" half of HierarchicalDecay."""
    depth: int
    message: Message
    edge: Edge


@dataclass(frozen=True)
class AncestorWalk:
    steps: list[AncestorStep]
    truncated: bool


async def walk_ancestors(
        session: AsyncSession,
        conversation: Conversation,
        message_id: UUID,
        max_depth: int = WALK_SAFETY_CAP,
):

    if max_depth<0:
        raise ValueError("max_depth cannot be negative")

    start = await get_message_in_conversation(session,conversation,message_id)

    if start is None:
        raise MessageNotFound(message_id)

    limit = min(max_depth,WALK_SAFETY_CAP) + 1 

    # The seed: "which edge points down at me?" The join to Message is the
    # conversation guard - it is what makes an ancestor in another
    # conversation not merely filtered out later, but never stepped onto.

    seed  = (
        select(
        Edge.id.label("edge_id"),
        Edge.parent_message_id.label("message_id"),
        literal(1).label("depth"),
    )
    .join(Message, Message.id == Edge.parent_message_id)
    .where(
        Edge.child_message_id == message_id,
        Message.conversation_id == conversation.id,
    )
    )

    walk=seed.cte("ancestor_walk",recursive=True)


     # The same question, asked of whatever the last pass found.
    #
    # Edge.child_message_id == walk.c.message_id is the direction of the whole
    # query. Swap it for parent_message_id and this walks *down* the tree - a
    # version that behaves perfectly on a straight-line chain and explodes on
    # a fork, because breadth is only 1 when you match on the unique column.


    step = (
        select(
            Edge.id,
            Edge.parent_message_id,
            walk.c.depth + literal(1)
        )
        .select_from(walk)
        .join(Edge, Edge.child_message_id == walk.c.message_id)
        .join(Message,Message.id==Edge.parent_message_id)
        .where(
            walk.c.depth < limit,
            Message.conversation_id==conversation.id
        )
    )

    # UNION ALL, not UNION: every row is already distinct, so deduplicating
    # would only buy a sort.
    walk = walk.union_all(step)

    # Only ids travelled through the recursion. Content and anchors are joined
    # out once, here, on primary keys.
    
    result =  await session.execute(
        select(walk.c.depth,Message,Edge)
        .select_from(walk)
        .join(Message,Message.id==walk.c.message_id)
        .join(Edge,Edge.id ==walk.c.edge_id)
        .order_by(walk.c.depth)
    )

    rows = result.all()

    return AncestorWalk(
        steps=[
            AncestorStep(depth=depth,message=message,edge=edge)
            for depth, message, edge in rows[:max_depth]
        ],
        truncated=len(rows)>max_depth
    )














