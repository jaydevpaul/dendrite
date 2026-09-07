"""Composition's front door - the one call generation makes.

Resolve which strategy applies, walk the chain that strategy will need, hand
both to it, and return the prompt along with the reason it looks the way it
does. Nothing here decides what a context should contain; that is each arm's
job, and keeping this file out of that decision is what keeps the five
comparable.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.context.base import (
    ComposedContext,
    ContextStrategy,
    StrategyRequest,
    anchor_from_walk
)

from app.context.strategies import (
    FullInheritance,
    HierarchicalDecay,
    HierarchicalDecayWithRetrieval,
    ParentOnly,
    SpanOnly
)

from app.llm.base import LLMClient
from app.models._shared import ALL_STRATEGIES,AnyStrategy
from app.models.conversation import Conversation
from app.services.ancestors import (
    WALK_SAFETY_CAP,
    MessageNotFound,
    StrategyResolution,
    resolve_strategy,
    walk_ancestors

)

from app.services.message import get_message_in_conversation

STRATEGIES = {
    "FullInheritance": FullInheritance(),
    "ParentOnly": ParentOnly(),
    "SpanOnly": SpanOnly(),
    "HierarchicalDecay": HierarchicalDecay(),
    "HierarchicalDecayWithRetrieval": HierarchicalDecayWithRetrieval(),
}


if set(STRATEGIES) != set(ALL_STRATEGIES):
    raise RuntimeError("Strategy dispatch is out of sync with the five strategies")

_mislabelled = [name for name,arm in STRATEGIES.items() if arm.name != name]

if _mislabelled:
    raise RuntimeError(
        f"Strategy dispatch entries name themselves something else: {_mislabelled}"
    )


@dataclass(frozen=True)
class Composition:
    """A composed prompt, and why this strategy produced it."""

    context: ComposedContext
    resolution: StrategyResolution

async def compose_context(
    session: AsyncSession,
    conversation: Conversation,
    message_id: UUID,
    llm: LLMClient,
    max_depth:int = WALK_SAFETY_CAP,
    strategies: Mapping[AnyStrategy,ContextStrategy] = STRATEGIES
):
    """Compose the prompt for a reply to this message."""

    question =  await get_message_in_conversation(session,conversation,message_id)

    if question is None:
        raise MessageNotFound(message_id)

    resolution = await resolve_strategy(
        session,conversation, message_id, max_depth
    )

    walk = await walk_ancestors(session,conversation,message_id,max_depth)

    request = StrategyRequest(
        session=session,
        llm=llm,
        question=question,
        anchor=anchor_from_walk(walk),
        walk=walk,
    )

    context = await strategies[resolution.strategy].compose(request)

    return Composition(context, resolution)





















































































