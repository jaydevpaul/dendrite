import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.llm.base import TextDelta
from app.services.generation import (
    GenerationDone,
    NotAUserMessage,
    start_generation,
    stream_generation
)

from app.api.deps import SessionDep,LLMDep, SessionFactoryDep
from app.api.sse import frame


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

# no-cache because a reply is generated once and never re-served from a cache.
# X-Accel-Buffering because nginx buffers a proxied response by default, which
# holds every chunk back until the reply is finished - the stream still works
# and arrives all at once, which reads as a very slow model rather than as a
# misconfigured proxy.
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


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


@router.post("/{message_id}/generate")
async def generate(
    message_id: uuid.UUID,
    conversation: OwnedConversation,
    session: SessionDep,
    llm: LLMDep,
    session_factory: SessionFactoryDep
):
    """Stream a reply to this user message."""

    try:
        prepared = await start_generation(session,conversation,message_id,llm)
    except MessageNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found") from exc
    except NotAUserMessage as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "A reply can only be generated for a user message",
        ) from exc

    async def events():

        yield frame(
            "start",
            {
                "assistant_message_id": str(prepared.assistant_message_id),
                "strategy": prepared.composition.context.strategy_used,
                "source": prepared.composition.resolution.source,
                "model": prepared.model,
            }
        )

        # A translation loop and nothing else. The service's events map one to
        # one onto the named events, so there is no bookkeeping here that could
        # end up disagreeing with what was written.

        async for event in stream_generation(prepared,llm,session_factory):
            if isinstance(event, TextDelta):
                yield frame("chunk",{"text": event.text})
            elif isinstance(event, GenerationDone):
                yield frame(
                    "done",
                    {
                        "generation_id": str(event.generation_id),
                        "input_tokens": event.input_tokens,
                        "output_tokens": event.output_tokens,
                        "degradations": event.degradations,
                    },
                )
            else:
                yield frame("error", {"detail": event.detail})

    return StreamingResponse(
        events(), media_type="text/event-stream", headers=SSE_HEADERS
    )












