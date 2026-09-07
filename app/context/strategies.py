"""The five context strategies, behind one interface.

Three of them need nothing but the walk. The two decay arms read summaries, and
the last one also embeds the question and ranks the summarized levels against
it. All five are frozen and tuned only through their constructors, so one
instance can serve every request - the session and the model client ride along
on the request instead.

Anything the arms share is in `base.py` and written once. Two arms rendering an
identical turn differently would land in the comparison as a quality difference
that has nothing to do with how context was composed.
"""

import asyncio
from dataclasses import dataclass

from app.context.decay import TieredDecay
from app.services.summary import load_summaries

from app.core.config import settings
from app.services.retrieval import promotion_count,rank_ancestors_by_similarity

from app.context.base import (
    StrategyRequest,
    full_turn,
    render_question,
    WALK_TRUNCATED,
    ComposedContext,
    SYSTEM_PROMPT,
    ensure_leading_user_turn,
    DecayFunction,
    SUMMARY_MISSING,
    summarised_turn,
    EMBEDDING_MISSING,
    render_decayed,
    retrieval_query_text,
    summarised_ids
)

from app.models._shared import AnyStrategy

class SpanOnlyRequiresAnchor(Exception):
    """SpanOnly was asked to compose for a continuation, which has no span."""

@dataclass(frozen=True)
class FullInheritance:
    """The entire ancestor chain at full text.

    This is the naive baseline and it is deliberately naive - no budget, no
    trimming, no cleverness. "Just resend the whole conversation" is the thing
    being measured, so anything smarter here would measure something else.
    """

    name: AnyStrategy = "FullInheritance"

    async def compose(self, request:StrategyRequest):
        # The walk comes back nearest-first; a prompt reads oldest-first.
        messages = [full_turn(step.message) for step in reversed(request.walk.steps)]
        messages.append(render_question(request.question,request.anchor))

        # This one promises the *entire* chain, so a walk that stopped short
        # really did degrade what it sent, and that has to be visible.

        degradations = [WALK_TRUNCATED] if request.walk.truncated else []


        return ComposedContext(
            system=SYSTEM_PROMPT,
            messages=ensure_leading_user_turn(messages=messages),
            strategy_used=self.name,
            degradations=degradations
        )
    



@dataclass(frozen=True)
class ParentOnly:
    """The immediate parent message only."""
    name: AnyStrategy = "ParentOnly"

    async def compose(self,request: StrategyRequest):
        messages=[]

        # Empty only when this question is the first message in the
        # conversation, which is legal - there is no parent to send.

        if request.walk.steps:
            messages.append(full_turn(request.walk.steps[0].message))

        messages.append(render_question(request.question,request.anchor))

        return ComposedContext(
            system=SYSTEM_PROMPT,
            messages=ensure_leading_user_turn(messages),
            strategy_used=self.name,
            # No degradation when the walk is cut short: this reads one level,
        )


@dataclass(frozen=True)
class SpanOnly:
    """The highlighted span only, no ancestors."""

    name: AnyStrategy = "SpanOnly"

    async def compose(self, request: StrategyRequest):
        if request.anchor is None:
            raise SpanOnlyRequiresAnchor(request.question.id)


        return ComposedContext(
            system=SYSTEM_PROMPT,
            messages=[render_question(request.question, request.anchor)],
            strategy_used=self.name,
        ) 


@dataclass(frozen=True)
class HierarchicalDecay:
    """The whole chain, with older ancestors sent as summaries."""

    decay: DecayFunction = TieredDecay()
    name: AnyStrategy="HierarchicalDecay"

    async def compose(self,request: StrategyRequest):
        steps = request.walk.steps
        fidelities = self.decay.assign(steps)

        summaries=await load_summaries(
            request.session,
            summarised_ids(steps,fidelities)
        )

        return render_decayed(request, fidelities,summaries,self.name)


@dataclass(frozen=True)
class HierarchicalDecayWithRetrieval:
    """Decay, then the most relevant summarized levels brought back to full
    text where they already sit."""

    decay: DecayFunction = TieredDecay()
    fraction: float = 1/3
    max_promotions: int  = 10
    timeout_seconds: float = settings.retrieval_timeout_seconds
    embedding_model: str = settings.embedding_model
    name: AnyStrategy = "HierarchicalDecayWithRetrieval"

    def __post_init__(self):
        if not 0<self.fraction <= 1:
            raise ValueError("fraction must be above 0 and at most 1")

        if self.max_promotions < 1:
            raise ValueError("max_promotions must be at least 1")

        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be above 0")


    async def compose(self,request:StrategyRequest):
        steps = request.walk.steps
        fidelities = self.decay.assign(steps)

        summaries = await load_summaries(request.session,summarised_ids(steps,fidelities))

        candidates = [
            step.message.id
            for step, fidelity in zip(steps,fidelities)
            if fidelity == "summary" and step.message.id  in summaries
        ]

        if not candidates:
            return render_decayed(request, fidelities, summaries, self.name)


        query_vector = await self._embed(request)

        if query_vector is None:
            return render_decayed(request, fidelities, summaries, "HierarchicalDecay")


        ranked = await rank_ancestors_by_similarity(
            request.session,candidates,query_vector,self.embedding_model
        )

        promoted = set(
            ranked[
                :promotion_count(len(candidates),self.fraction, self.max_promotions)
            ]
        )

        fidelities = [
            "full" if step.message.id in promoted else fidelity
            for step, fidelity in zip(steps, fidelities)
        ]

        extra = [EMBEDDING_MISSING] if len(ranked) < len(candidates) else []

        return render_decayed(request,fidelities, summaries,self.name,extra)

    async def _embed(self, request: StrategyRequest):
        """The query vector, or None if the embedding service did not answer."""

        try:
            return await asyncio.wait_for(
                request.llm.embed(
                    retrieval_query_text(request.question,request.anchor)
                ),
                timeout = self.timeout_seconds
            )
        except Exception:
            return None
