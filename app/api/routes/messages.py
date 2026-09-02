import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import SessionDep
from app.api.routes.conversations import OwnedConversation

from app.schemas.ancestors import AncestorChain, StrategyResolutionOut

from app.services.ancestors import (
    WALK_SAFETY_CAP,
    MessageNotFound,
    resolve_strategy,
    walk_ancestors,
)

from app.schemas.message import(
    ConversationGraph,
    EdgeOut,
    MessageCreate,
    MessageCreated,
    MessageOut,
)
from app.services.message import (
    InvalidAnchor,
    ParentNotFound,
    RootAlreadyExists,
    create_message,
    list_conversation_graph,
)


# Nested under the conversation on purpose. The id in the path feeds
# OwnedConversation, so a handler here cannot run without the ownership filter
# having run first - and every route stays under the /conversations prefix the
# Vite dev proxy already forwards.

router = APIRouter(prefix="/conversations/{conversation_id}/messages", tags=["message"])

@router.post("",response_model=MessageCreated, status_code=status.HTTP_201_CREATED)
async def create(
    body: MessageCreate, conversation: OwnedConversation, session: SessionDep
):
    try:
        message, edge = await create_message(session,conversation,body)
    except ParentNotFound as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Parent message not found"
        ) from exc
    except RootAlreadyExists as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This conversation already has a root message"
        ) from exc
    except InvalidAnchor as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)
        ) from exc

    return MessageCreated(
        message=MessageOut.model_validate(message),
        edge=EdgeOut.model_validate(edge) if edge is not None else None,
    )


@router.get("", response_model=ConversationGraph)
async def list_all(conversation: OwnedConversation, session: SessionDep):
    messages, edges = await list_conversation_graph(session, conversation)

    return ConversationGraph(
        messages=[MessageOut.model_validate(m) for m in messages],
        edges=[EdgeOut.model_validate(e) for e in edges],
    )

@router.get("/{message_id}/ancestors", response_model=AncestorChain)
async def ancestors(
    message_id: uuid.UUID,
    conversation: OwnedConversation,
    session: SessionDep,
    max_depth: Annotated[int, Query(ge=0, le=WALK_SAFETY_CAP)] = WALK_SAFETY_CAP,
):
    """The chain above a message, plus the strategy that will compose it."""

    try:
        walk = await walk_ancestors(session, conversation, message_id, max_depth)
        resolved = await resolve_strategy(session, conversation, message_id)
    except MessageNotFound as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Message not found"
        ) from exc

    return AncestorChain(
        steps=walk.steps,
        truncated=walk.truncated,
        strategy=StrategyResolutionOut.model_validate(resolved),
    )
