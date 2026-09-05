"""The three strategies that need no summaries and no retrieval.

The other two arrive later behind the same interface. All three here are frozen
and take no arguments, so one instance can serve every request - the session and
the model client ride along on the request instead.
"""

from dataclasses import dataclass

from app.context.base import (
    StrategyRequest,
    full_turn,
    render_question,
    WALK_TRUNCATED,
    ComposedContext,
    SYSTEM_PROMPT,
    ensure_leading_user_turn
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

















