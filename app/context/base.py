"""Context composition - the types, and the interface section 5 locks.

Five implementations sit behind `ContextStrategy`: section 5's arms 1-3 in
`strategies.py`, the two decay arms in C3-C5. Section 7 compares them against
each other, so everything the arms *share* lives here and is written exactly
once. A difference in how two arms render the same question would show up in
the eval as a quality difference that has nothing to do with context
composition.
"""
from dataclasses import dataclass,field
from app.llm.base import LLMClient, PromptMessage, PromptRole
from collections.abc import Sequence

from typing import Any,Protocol,cast,Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.models._shared import AnyStrategy
from app.models.edge import Edge
from app.models.message import Message
from app.services.ancestors import AncestorWalk, AncestorStep


SYSTEM_PROMPT = (
    "You are answering inside a branching conversation. The turns before the "
    "final question are its ancestors, oldest first, and may be an incomplete "
    "record of the conversation. A turn whose content begins with [summarised] "
    "is a summary of what that participant said, not their own words. If the "
    "final question quotes a highlighted passage, that passage is what the user "
    "is asking about. Answer the final question."
)

WALK_TRUNCATED = "walk_truncated"

# An ancestor the decay function marked for summarizing that had no summary
# row, so its full text went instead. Costlier, still correct - and it needs
# its own name, because "the walk was cut short" and "we paid full price for a
# level that should have been cheap" are different findings with different
# fixes.
SUMMARY_MISSING = "summary_missing"

SUMMARY_MARKER = "[summarised]"


# prepended when the oldest verbatim turn is an assistant turn, since
# messages[0] must be a user message on every current provider.
EARLIER_PLACEHOLDER = PromptMessage(
    role="user", content="(earlier in the conversation)"
)


@dataclass(frozen=True)
class Anchor:
    """The highlighted span a branch was created from."""

    start: int
    end: int
    text: str

    @classmethod
    def from_edge(cls,edge:Edge):

        if edge.anchor_start is None:
            return None

        return cls(
            start=edge.anchor_start,
            end=cast(int, edge.anchor_end),
            text=cast(str, edge.anchored_text),
        )


def anchor_from_walk(walk: AncestorWalk):
    if not walk.steps:
        return None

    return Anchor.from_edge(walk.steps[0].edge)


@dataclass(frozen=True)
class StrategyRequest:
    session: AsyncSession
    llm: LLMClient
    question: Message
    anchor: Anchor | None
    walk: AncestorWalk


@dataclass(frozen=True)
class ComposedContext:
    """The result of composition."""

    system: str
    messages: list[PromptMessage]
    strategy_used: AnyStrategy
    degradations: list[str] = field(default_factory=list)

    def as_payload(self):

        return {
            "system":self.system,
            "messages":[
                {"role":message.role, "content":message.content}
                for message in self.messages
            ]
        }

# There is no "drop" level on purpose. Older ancestors get shorter, never
# removed, so decay and full inheritance cover exactly the same ancestors and
# differ only in how much of each one is sent. That is what lets a token saving
# be credited to summarizing rather than to having quietly sent less.
Fidelity = Literal["full", "summary"]


class DecayFunction(Protocol):
    """How fidelity falls off as ancestors get older"""

    def assign(self, steps: Sequence[AncestorStep]) -> list[Fidelity]: ...

class ContextStrategy(Protocol):
    """The swappable interface. A strategy names itself rather than being
    labelled by its caller, so that when one falls back to a simpler strategy,
    what gets recorded is what actually ran and not what was asked for."""
    name: AnyStrategy

    async def compose(self,request: StrategyRequest): ...


def full_turn(message: Message):

    return PromptMessage(
        role=cast(PromptRole,message.role),
        content=message.content
    )


def summarised_turn(message:Message, summary_text:str):
    """A summarized ancestor"""

    return PromptMessage(
        role=cast(PromptRole,message.role),
        content=f"{SUMMARY_MARKER} {summary_text}"
    )    




def render_question(question: Message, anchor: Anchor|None):

    if anchor is None:
        return PromptMessage(role="user",content=question.content)

    content=(
        "Highlighted from the previous message:\n"
        '"""\n'
        f"{anchor.text}\n"
        '"""\n\n'
        f"{question.content}"
    )

    return PromptMessage(role="user", content=content)


def ensure_leading_user_turn(messages: list[PromptMessage]) -> list[PromptMessage]:
    if messages and messages[0].role == "assistant":
        return [EARLIER_PLACEHOLDER, *messages]

    return messages