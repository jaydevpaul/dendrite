"""The one entry point generation calls: resolve, walk, dispatch, return.

These run against the real resolver and the real walk, because that coupling is
the whole of what `compose_context` does. A hand-built resolution handed to a
hand-built dispatch would pass while the two disagreed about which edge holds
the anchor.

Two tests here exist to pin down decisions rather than behaviour, and are
labelled as such: composing from the blank assistant row, and the database
constraint that makes a span-less SpanOnly unreachable.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.context.base import SUMMARY_MARKER, SYSTEM_PROMPT
from app.context.compose import STRATEGIES, Composition, compose_context
from app.context.decay import TieredDecay
from app.context.strategies import HierarchicalDecay
from app.llm.fake import FakeLLMClient
from app.models._shared import ALL_STRATEGIES
from app.models.edge import Edge
from app.services.ancestors import MessageNotFound
from tests.graph_builders import (
    ANCHOR_TEXT,
    QUESTION_TEXT,
    a_deep_question,
    a_question,
    link,
    new_conversation,
    new_message,
    new_user,
)

def summarised_turns(context):
    return [
        turn for turn in context.messages if turn.content.startswith(SUMMARY_MARKER)
    ]


async def compose(session, conversation, question, **kwargs):
    return await compose_context(
        session, conversation, question.id, FakeLLMClient(), **kwargs
    )


# --- the dispatch table ---------------------------------------------------


def test_every_strategy_has_exactly_one_entry():
    """A sixth arm is registered in one place. If the table could be missing a
    key, the arm that got left out would fail at the moment a real conversation
    resolved to it, which is a long way from where the mistake was made."""
    assert set(STRATEGIES) == set(ALL_STRATEGIES)
    assert len(STRATEGIES) == len(ALL_STRATEGIES)


def test_each_entry_answers_to_its_own_key():
    """The key says which strategy was resolved; the instance stamps its own
    name onto the result. Those are two different sources for one fact, and a
    strategy built with its arguments in the wrong order would put a tuning
    object into `name` without raising - so the two are checked against each
    other rather than trusted."""
    for name, strategy in STRATEGIES.items():
        assert strategy.name == name


# --- resolve, then dispatch ----------------------------------------------


async def test_a_branch_composes_the_span_alone(session):
    """A branch edge with no override is section 5's SpanOnly default, and the
    span it composes comes off that same edge."""
    conversation, question, _ = await a_question(session, default_strategy="ParentOnly")

    result = await compose(session, conversation, question)

    assert result.resolution.strategy == "SpanOnly"
    assert result.resolution.source == "branch_default"
    assert result.context.strategy_used == "SpanOnly"
    assert len(result.context.messages) == 1
    assert ANCHOR_TEXT in result.context.messages[0].content


async def test_a_continuation_composes_the_conversation_default(session):
    conversation, question, ancestors = await a_question(
        session, default_strategy="ParentOnly", anchor=None
    )

    result = await compose(session, conversation, question)

    assert result.resolution.strategy == "ParentOnly"
    assert result.resolution.source == "conversation_default"
    assert result.context.strategy_used == "ParentOnly"
    # The parent is an assistant turn, so the placeholder that keeps a user
    # message first goes in front of it - the one arm where that fires.
    assert [turn.content for turn in result.context.messages[-2:]] == [
        ancestors[-1].content,
        QUESTION_TEXT,
    ]
    assert result.context.messages[0].role == "user"
    assert len(result.context.messages) == 3


async def test_an_override_on_the_edge_beats_the_conversation_default(session):
    conversation, question, ancestors = await a_question(
        session, default_strategy="ParentOnly", override="FullInheritance"
    )

    result = await compose(session, conversation, question)

    assert result.resolution.strategy == "FullInheritance"
    assert result.resolution.source == "edge"
    assert result.context.strategy_used == "FullInheritance"
    assert len(result.context.messages) == len(ancestors) + 1


async def test_the_deciding_edge_travels_with_the_prompt(session):
    """The start of a stream reports which strategy is being used and why, so
    the reason has to survive composition rather than being recomputed by
    whoever wants to display it."""
    conversation, question, _ = await a_question(session)
    edge_id = await session.scalar(
        select(Edge.id).where(Edge.child_message_id == question.id)
    )

    result = await compose(session, conversation, question)

    assert isinstance(result, Composition)
    assert result.resolution.edge_id == edge_id
    assert result.context.system == SYSTEM_PROMPT


# --- which message composition starts from -------------------------------


async def test_composing_from_the_blank_assistant_row_answers_differently(session):
    """Not a bug being reproduced - the reason generation must compose before it
    inserts anything.

    The reply row is created blank and then streamed into, and walking from
    *it* puts the branch edge one level further up, where the resolver stops at
    a branch boundary and answers with the conversation default. Nothing raises
    and no context is malformed; branching simply stops working, and the
    comparison would report five strategies while running four.
    """
    conversation, question, _ = await a_question(
        session, default_strategy="FullInheritance"
    )

    blank = await new_message(session, conversation, "assistant", "")
    await link(session, question, blank)
    await session.commit()

    from_question = await compose(session, conversation, question)
    from_blank = await compose(session, conversation, blank)

    assert from_question.resolution.strategy == "SpanOnly"
    assert from_blank.resolution.strategy == "FullInheritance"
    assert from_blank.resolution.source == "branch_boundary"


# --- degradations --------------------------------------------------------


async def test_the_result_records_the_arm_that_ran_not_the_one_resolved(session):
    """A degraded run is spotted by comparing what was asked for against what
    the database says happened, so those two have to be able to disagree. Here
    retrieval was resolved, the embedder was down, and plain decay is what
    actually composed the prompt."""
    conversation, question, _ = await a_deep_question(
        session, default_strategy="HierarchicalDecayWithRetrieval"
    )

    result = await compose_context(
        session,
        conversation,
        question.id,
        FakeLLMClient(fail_on_embed=True),
    )

    assert result.resolution.strategy == "HierarchicalDecayWithRetrieval"
    assert result.context.strategy_used == "HierarchicalDecay"


async def test_a_clean_run_agrees_with_itself(session):
    """The other half of the comparison above: with nothing wrong, the arm that
    ran is the arm that was resolved. Without this, a composer that always
    reported the simpler arm would pass the test above."""
    conversation, question, _ = await a_deep_question(
        session, default_strategy="HierarchicalDecay"
    )

    result = await compose(session, conversation, question)

    assert result.resolution.strategy == "HierarchicalDecay"
    assert result.context.strategy_used == "HierarchicalDecay"
    assert summarised_turns(result.context)


async def test_one_depth_limit_reaches_both_the_resolver_and_the_walk(session):
    """Both queries climb, and a cap that only reached one of them would give a
    strategy chosen at one depth and a chain gathered at another."""
    conversation, question, _ = await a_question(
        session, default_strategy="FullInheritance", anchor=None
    )

    result = await compose(session, conversation, question, max_depth=2)

    assert result.resolution.source == "depth_cap"
    assert "walk_truncated" in result.context.degradations


# --- what compose is and is not ------------------------------------------


async def test_composing_writes_nothing(session):
    """Composition happens before the assistant row exists and is committed
    separately from it, so it has to be a read."""
    conversation, question, _ = await a_deep_question(
        session, default_strategy="HierarchicalDecayWithRetrieval"
    )

    await compose(session, conversation, question)

    assert not session.new
    assert not session.dirty
    assert not session.deleted


async def test_a_message_from_another_conversation_is_not_composable(session):
    """Same answer as the walk and the message service give: the id is simply
    not in this conversation. Composition is what pulls ancestor text into a
    prompt, so this is the last place a stranger's message could arrive."""
    conversation, _, _ = await a_question(session)
    other_user = await new_user(session, email="someone-else@example.com")
    other = await new_conversation(session, other_user)
    stranger = await new_message(session, other, "user", "not yours")
    await session.commit()

    with pytest.raises(MessageNotFound):
        await compose(session, conversation, stranger)


async def test_the_table_can_be_swapped_for_tuned_arms(session):
    """The tier is a constructor argument so it can be varied, and varying it
    has to reach composition without editing the module."""
    conversation, question, _ = await a_deep_question(
        session, default_strategy="HierarchicalDecay", summarised="all"
    )

    default = await compose(session, conversation, question)
    shallow = await compose(
        session,
        conversation,
        question,
        strategies={
            **STRATEGIES,
            "HierarchicalDecay": HierarchicalDecay(TieredDecay(full_depth=1)),
        },
    )

    assert len(summarised_turns(shallow.context)) > len(
        summarised_turns(default.context)
    )


# --- why SpanOnly is allowed to raise ------------------------------------


async def test_span_only_cannot_be_stored_on_an_unanchored_edge(session):
    """The fact the composer relies on, written down as a test.

    SpanOnly refuses to compose without a span, and the composer does not catch
    that refusal - a fallback there would be protecting against a state the
    database will not hold. This is checked against the constraint rather than
    the request schema, because the schema is one caller and these tests are
    another.
    """
    conversation, question, _ = await a_question(session, anchor=None)
    orphan = await new_message(session, conversation, "assistant", "a reply")
    await session.flush()

    session.add(
        Edge(
            parent_message_id=question.id,
            child_message_id=orphan.id,
            strategy_override="SpanOnly",
        )
    )

    with pytest.raises(IntegrityError):
        await session.flush()

    await session.rollback()


async def test_a_branch_that_resolves_to_span_only_always_has_its_span(session):
    """The other half: when resolution does answer SpanOnly, the anchor the arm
    needs is on the very edge that decided it, so the two cannot disagree."""
    conversation, question, _ = await a_question(session, override="SpanOnly")

    result = await compose(session, conversation, question)

    assert result.resolution.strategy == "SpanOnly"
    assert result.resolution.source == "edge"
    assert ANCHOR_TEXT in result.context.messages[0].content
