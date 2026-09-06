"""Context types, the strategy interface, and four of the five strategies.

These run against the real ancestor walk, not a hand-built one: the anchor a
strategy composes comes off the edge one level up, and that coupling is only
real if a real recursive query produced the step.

The cross-strategy tests at the bottom are the ones that matter most. The whole
project compares these strategies against each other, so anything that differs
between them for a reason *other* than which ancestors are sent will show up in
the results as a difference the experiment cannot explain.
"""

import pytest

from app.context.base import (
    SUMMARY_MARKER,
    SUMMARY_MISSING,
    SYSTEM_PROMPT,
    WALK_TRUNCATED,
    Anchor,
    ComposedContext,
    StrategyRequest,
    anchor_from_walk,
    ensure_leading_user_turn,
    render_question,
)
from app.context.decay import TieredDecay
from app.context.strategies import (
    FullInheritance,
    HierarchicalDecay,
    ParentOnly,
    SpanOnly,
    SpanOnlyRequiresAnchor,
)
from app.llm.base import PromptMessage
from app.llm.fake import FakeLLMClient
from app.models.message import Message
from app.services.ancestors import walk_ancestors
from tests.conftest import counting_queries
from tests.graph_builders import (
    ANCHOR_TEXT,
    PARENT_TEXT,
    SPAN,
    chain_of,
    link,
    new_conversation,
    new_message,
    new_summary,
    new_user,
)

QUESTION_TEXT = "What does that cost me?"

SIMPLE_STRATEGIES = [FullInheritance(), ParentOnly(), SpanOnly()]

# Every arm that exists so far. The cross-strategy tests at the bottom run
# against this list, so a fifth arm joins it and immediately has to answer for
# the things all of them hold constant.
BUILT_STRATEGIES = [*SIMPLE_STRATEGIES, HierarchicalDecay()]


# --- builders -------------------------------------------------------------


async def a_branch(session, trunk_length=3, anchor=SPAN):
    """A trunk of continuations, an assistant reply, then the question.

    `chain_of` alternates roles from a user root, so a trunk of 3 is
    user/assistant/user; the reply carries PARENT_TEXT so the anchor offsets
    point at real words, and the question hangs off it. With `anchor=None` the
    same shape is a continuation instead of a branch.

    Returns the conversation, the question, and the ancestors oldest-first -
    which is prompt order, so a test can compare against the list directly.
    """
    user = await new_user(session)
    conversation = await new_conversation(session, user)
    trunk = await chain_of(session, conversation, trunk_length)

    reply = await new_message(session, conversation, "assistant", PARENT_TEXT)
    await link(session, trunk[-1], reply)

    question = await new_message(session, conversation, "user", QUESTION_TEXT)
    await link(session, reply, question, anchor=anchor)

    await session.commit()
    return conversation, question, [*trunk, reply]


async def a_request(session, conversation, question, max_depth=200):
    """What the composer will assemble: walk the chain, hand it to a strategy."""
    walk = await walk_ancestors(session, conversation, question.id, max_depth=max_depth)

    return StrategyRequest(
        session=session,
        llm=FakeLLMClient(),
        question=question,
        anchor=anchor_from_walk(walk),
        walk=walk,
    )


# --- the shared pieces, which no strategy may re-implement ----------------


def test_a_question_without_an_anchor_is_sent_as_typed():
    question = Message(role="user", content=QUESTION_TEXT)

    turn = render_question(question, None)

    assert turn == PromptMessage(role="user", content=QUESTION_TEXT)


def test_a_question_with_an_anchor_carries_the_span_and_the_question():
    question = Message(role="user", content=QUESTION_TEXT)
    anchor = Anchor(start=0, end=len(ANCHOR_TEXT), text=ANCHOR_TEXT)

    turn = render_question(question, anchor)

    assert turn.role == "user"
    assert ANCHOR_TEXT in turn.content
    assert QUESTION_TEXT in turn.content
    # The span is context for the question, so it comes first.
    assert turn.content.index(ANCHOR_TEXT) < turn.content.index(QUESTION_TEXT)


def test_an_assistant_leading_prompt_gets_the_placeholder():
    """Every provider requires the first message to be from the user."""
    messages = [
        PromptMessage(role="assistant", content="pgvector is enough."),
        PromptMessage(role="user", content=QUESTION_TEXT),
    ]

    result = ensure_leading_user_turn(messages)

    assert result[0].role == "user"
    assert result[1:] == messages


def test_a_user_leading_prompt_is_left_alone():
    messages = [PromptMessage(role="user", content=QUESTION_TEXT)]

    assert ensure_leading_user_turn(messages) == messages


def test_the_payload_is_the_prompt_and_nothing_else():
    """The stored payload has to be replayable, so it holds exactly what was
    sent. The strategy name has its own column, and a degradation can be worked
    out later by comparing the strategy asked for against the one recorded."""
    context = ComposedContext(
        system=SYSTEM_PROMPT,
        messages=[PromptMessage(role="user", content=QUESTION_TEXT)],
        strategy_used="SpanOnly",
        degradations=[WALK_TRUNCATED],
    )

    assert context.as_payload() == {
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": QUESTION_TEXT}],
    }


# --- the anchor comes off the edge one level up ---------------------------


async def test_a_branch_edge_yields_the_anchor(session):
    conversation, question, _ = await a_branch(session)

    request = await a_request(session, conversation, question)

    assert request.anchor == Anchor(start=SPAN[0], end=SPAN[1], text=ANCHOR_TEXT)


async def test_a_continuation_yields_no_anchor(session):
    conversation, question, _ = await a_branch(session, anchor=None)

    request = await a_request(session, conversation, question)

    assert request.anchor is None


async def test_a_root_question_yields_no_anchor(session):
    """An empty walk means no parent edge at all, so there is nothing to read an
    anchor off - and no ancestors to send either."""
    user = await new_user(session)
    conversation = await new_conversation(session, user)
    question = await new_message(session, conversation, "user", QUESTION_TEXT)
    await session.commit()

    request = await a_request(session, conversation, question)

    assert request.anchor is None
    assert request.walk.steps == []


# --- FullInheritance ------------------------------------------------------


async def test_full_inheritance_sends_every_ancestor_oldest_first(session):
    conversation, question, ancestors = await a_branch(session)

    context = await FullInheritance().compose(
        await a_request(session, conversation, question)
    )

    assert [turn.content for turn in context.messages[:-1]] == [
        ancestor.content for ancestor in ancestors
    ]


async def test_full_inheritance_preserves_ancestor_roles(session):
    conversation, question, ancestors = await a_branch(session)

    context = await FullInheritance().compose(
        await a_request(session, conversation, question)
    )

    assert [turn.role for turn in context.messages] == [
        *(ancestor.role for ancestor in ancestors),
        "user",
    ]


async def test_full_inheritance_needs_no_placeholder(session):
    """The chain climbs to the very first message, which is always a user
    message, so nothing should be prepended here."""
    conversation, question, ancestors = await a_branch(session)

    context = await FullInheritance().compose(
        await a_request(session, conversation, question)
    )

    assert len(context.messages) == len(ancestors) + 1


async def test_full_inheritance_on_a_root_question_sends_only_the_question(session):
    user = await new_user(session)
    conversation = await new_conversation(session, user)
    question = await new_message(session, conversation, "user", QUESTION_TEXT)
    await session.commit()

    context = await FullInheritance().compose(
        await a_request(session, conversation, question)
    )

    assert context.messages == [PromptMessage(role="user", content=QUESTION_TEXT)]


async def test_full_inheritance_reports_a_truncated_walk(session):
    """This strategy promises the whole chain, so a walk that stopped short is a
    real degradation of what it sent and has to be visible."""
    conversation, question, _ = await a_branch(session)

    context = await FullInheritance().compose(
        await a_request(session, conversation, question, max_depth=2)
    )

    assert context.degradations == [WALK_TRUNCATED]
    assert len(context.messages) == 3          # two ancestors plus the question


async def test_a_truncated_walk_can_still_start_on_a_user_turn(session):
    """Stopping the walk early makes the oldest surviving turn arbitrary, so the
    placeholder earns its keep here even though a full chain never needs it."""
    conversation, question, _ = await a_branch(session)

    context = await FullInheritance().compose(
        await a_request(session, conversation, question, max_depth=1)
    )

    assert context.messages[0].role == "user"


# --- ParentOnly -----------------------------------------------------------


async def test_parent_only_sends_exactly_the_parent(session):
    conversation, question, ancestors = await a_branch(session)

    context = await ParentOnly().compose(
        await a_request(session, conversation, question)
    )

    # messages[-2], not [:-1]: the placeholder leads this strategy's prompt.
    assert context.messages[-2].content == ancestors[-1].content
    assert PARENT_TEXT not in context.messages[-1].content


async def test_parent_only_prepends_the_placeholder(session):
    """A question's parent is an assistant reply in every shape that gets here,
    so this is the strategy the placeholder exists for."""
    conversation, question, _ = await a_branch(session)

    context = await ParentOnly().compose(
        await a_request(session, conversation, question)
    )

    assert [turn.role for turn in context.messages] == ["user", "assistant", "user"]
    assert context.messages[0].content != PARENT_TEXT


async def test_parent_only_ignores_truncation(session):
    """It reads one level, so a walk that stopped 199 levels above it changed
    nothing about what was sent. Claiming a degradation here would poison the
    count of how often the real degradations fire."""
    conversation, question, _ = await a_branch(session)

    context = await ParentOnly().compose(
        await a_request(session, conversation, question, max_depth=1)
    )

    assert context.degradations == []


async def test_parent_only_on_a_root_question_sends_only_the_question(session):
    user = await new_user(session)
    conversation = await new_conversation(session, user)
    question = await new_message(session, conversation, "user", QUESTION_TEXT)
    await session.commit()

    context = await ParentOnly().compose(
        await a_request(session, conversation, question)
    )

    assert context.messages == [PromptMessage(role="user", content=QUESTION_TEXT)]


# --- SpanOnly -------------------------------------------------------------


async def test_span_only_sends_one_turn_and_no_ancestors(session):
    conversation, question, _ = await a_branch(session)

    context = await SpanOnly().compose(
        await a_request(session, conversation, question)
    )

    assert len(context.messages) == 1
    assert ANCHOR_TEXT in context.messages[0].content
    assert QUESTION_TEXT in context.messages[0].content
    assert PARENT_TEXT not in context.messages[0].content


async def test_span_only_refuses_a_continuation(session):
    """A continuation has no highlighted span, so this strategy has nothing to
    send. Nothing in the app can ask for it there, but the evaluation harness
    names strategies directly - and quietly falling back to another one would
    file that strategy's numbers under this one."""
    conversation, question, _ = await a_branch(session, anchor=None)

    with pytest.raises(SpanOnlyRequiresAnchor):
        await SpanOnly().compose(await a_request(session, conversation, question))


async def test_span_only_never_degrades(session):
    conversation, question, _ = await a_branch(session)

    context = await SpanOnly().compose(
        await a_request(session, conversation, question, max_depth=1)
    )

    assert context.degradations == []


# --- HierarchicalDecay ----------------------------------------------------


async def a_deep_branch(session, summarised="older"):
    """A branch with seven ancestors, deep enough for the default tier to bite.

    Depths run 1 to 7, so under the three-level tier the newest three are sent
    in full and the oldest four drop to summaries - which makes `ancestors[-3:]`
    the full ones and `ancestors[:-3]` the summarized ones in every test below.

    `summarised` says which ancestors actually have a summary row. "older" is
    the ordinary case; "none" is a chain nothing has summarized yet; "all"
    gives even the full-tier levels one, so a test can check the tier decides
    what is sent rather than whatever happens to be available.
    """
    conversation, question, ancestors = await a_branch(session, trunk_length=6)

    to_summarise = {"older": ancestors[:-3], "none": [], "all": ancestors}[summarised]

    for ancestor in to_summarise:
        await new_summary(
            session, ancestor, summary_text=f"a summary of {ancestor.content}"
        )

    await session.commit()
    return conversation, question, ancestors


def summarised_turns(context):
    return [
        turn for turn in context.messages if turn.content.startswith(SUMMARY_MARKER)
    ]


async def test_decay_covers_every_ancestor(session):
    """Same ancestors as full inheritance, and that is the whole design. If
    decay reached fewer levels, a saving in tokens could be explained by having
    sent less of the conversation rather than by summarizing what it sent."""
    conversation, question, ancestors = await a_deep_branch(session)
    request = await a_request(session, conversation, question)

    decayed = await HierarchicalDecay().compose(request)
    full = await FullInheritance().compose(request)

    assert len(decayed.messages) == len(ancestors) + 1
    assert len(decayed.messages) == len(full.messages)


async def test_the_older_levels_are_sent_as_summaries(session):
    conversation, question, ancestors = await a_deep_branch(session)

    context = await HierarchicalDecay().compose(
        await a_request(session, conversation, question)
    )

    assert [turn.content for turn in context.messages[:4]] == [
        f"{SUMMARY_MARKER} a summary of {ancestor.content}"
        for ancestor in ancestors[:-3]
    ]


async def test_the_newest_levels_are_full_even_when_a_summary_exists(session):
    """Every ancestor here has a summary, including the three nearest ones. The
    tier decides what gets sent, not what happens to be in the table."""
    conversation, question, ancestors = await a_deep_branch(session, summarised="all")

    context = await HierarchicalDecay().compose(
        await a_request(session, conversation, question)
    )

    assert [turn.content for turn in context.messages[-4:-1]] == [
        ancestor.content for ancestor in ancestors[-3:]
    ]


async def test_the_summarised_levels_stay_in_place(session):
    """Oldest first, in the same order full inheritance sends them. A summary is
    a shorter version of a turn in position, not a separate excerpt appended
    somewhere else in the prompt."""
    conversation, question, ancestors = await a_deep_branch(session)

    context = await HierarchicalDecay().compose(
        await a_request(session, conversation, question)
    )

    assert summarised_turns(context) == context.messages[:4]
    assert len(summarised_turns(context)) == len(ancestors) - 3


async def test_a_summarised_level_keeps_the_ancestor_role(session):
    """Decay changes how much of a turn is sent, never who said it. Moving a
    summary to another voice would invent a speaker who never spoke."""
    conversation, question, _ = await a_deep_branch(session)
    request = await a_request(session, conversation, question)

    decayed = await HierarchicalDecay().compose(request)
    full = await FullInheritance().compose(request)

    assert [turn.role for turn in decayed.messages] == [
        turn.role for turn in full.messages
    ]


async def test_a_fully_summarised_chain_reports_nothing(session):
    conversation, question, _ = await a_deep_branch(session)

    context = await HierarchicalDecay().compose(
        await a_request(session, conversation, question)
    )

    assert context.degradations == []


async def test_a_missing_summary_falls_back_to_full_text(session):
    """Summarizing runs behind the conversation, so a level marked for a summary
    that has not got one yet is the ordinary state rather than a fault. Full
    text costs more and stays correct, which is the right way round."""
    conversation, question, ancestors = await a_deep_branch(session, summarised="none")

    context = await HierarchicalDecay().compose(
        await a_request(session, conversation, question)
    )

    assert [turn.content for turn in context.messages[:-1]] == [
        ancestor.content for ancestor in ancestors
    ]
    assert summarised_turns(context) == []


async def test_the_missing_summary_is_reported_once_for_the_whole_compose(session):
    """Four levels wanted a summary and none of them had one, and that is one
    finding about one composition. Recorded per ancestor it would be a list
    holding the same name four times, which the evaluation would have to
    de-duplicate before it could report how often this happens."""
    conversation, question, _ = await a_deep_branch(session, summarised="none")

    context = await HierarchicalDecay().compose(
        await a_request(session, conversation, question)
    )

    assert context.degradations == [SUMMARY_MISSING]


async def test_a_partly_summarised_chain_reports_it_once_too(session):
    """One level short is the same finding as four levels short, and the levels
    that do have summaries are still sent as summaries."""
    conversation, question, ancestors = await a_deep_branch(session, summarised="none")
    await new_summary(session, ancestors[0], summary_text="the oldest, shortened")
    await session.commit()

    context = await HierarchicalDecay().compose(
        await a_request(session, conversation, question)
    )

    assert context.degradations == [SUMMARY_MISSING]
    assert context.messages[0].content == f"{SUMMARY_MARKER} the oldest, shortened"


async def test_it_reports_a_truncated_walk(session):
    """This arm climbs to the root the same way full inheritance does, so a walk
    that stopped short really did cut what it sent. Parent-only stays silent
    about the same cap because the cap changed nothing for it."""
    conversation, question, _ = await a_deep_branch(session)

    context = await HierarchicalDecay().compose(
        await a_request(session, conversation, question, max_depth=3)
    )

    assert context.degradations == [WALK_TRUNCATED]


async def test_both_degradations_can_fire_at_once(session):
    """A walk cut short and a level with no summary are separate findings with
    separate fixes, so both are recorded rather than one standing in for the
    other."""
    conversation, question, _ = await a_deep_branch(session, summarised="none")

    context = await HierarchicalDecay().compose(
        await a_request(session, conversation, question, max_depth=5)
    )

    assert context.degradations == [WALK_TRUNCATED, SUMMARY_MISSING]


async def test_the_decay_function_is_swappable(session):
    """The tier is handed in rather than written into the strategy. That is what
    makes this a family of arms instead of one algorithm, and the evaluation
    sweeps it."""
    conversation, question, ancestors = await a_deep_branch(session, summarised="all")
    request = await a_request(session, conversation, question)

    shallow = await HierarchicalDecay(TieredDecay(full_depth=1)).compose(request)
    default = await HierarchicalDecay().compose(request)

    assert len(summarised_turns(shallow)) == len(ancestors) - 1
    assert len(summarised_turns(default)) == len(ancestors) - 3


async def test_a_chain_inside_the_tier_asks_the_database_nothing(session, engine):
    """Three ancestors and three full levels, so nothing is marked for
    summarizing and there is nothing to look up. A query here would be one the
    user waits for and gets nothing from."""
    conversation, question, ancestors = await a_branch(session, trunk_length=2)
    request = await a_request(session, conversation, question)

    with counting_queries(engine) as sent:
        context = await HierarchicalDecay().compose(request)

    assert sent == []
    assert context.degradations == []
    assert [turn.content for turn in context.messages[:-1]] == [
        ancestor.content for ancestor in ancestors
    ]


async def test_the_whole_chain_costs_one_summary_query(session, engine):
    """One read covering every summarized level. Looking each one up inside the
    render loop would be a round trip per level, and this runs while the user is
    waiting for the first token."""
    conversation, question, _ = await a_deep_branch(session)
    request = await a_request(session, conversation, question)

    with counting_queries(engine) as sent:
        await HierarchicalDecay().compose(request)

    assert len(sent) == 1


async def test_decay_on_a_root_question_sends_only_the_question(session):
    user = await new_user(session)
    conversation = await new_conversation(session, user)
    question = await new_message(session, conversation, "user", QUESTION_TEXT)
    await session.commit()

    context = await HierarchicalDecay().compose(
        await a_request(session, conversation, question)
    )

    assert context.messages == [PromptMessage(role="user", content=QUESTION_TEXT)]
    assert context.degradations == []


async def test_a_truncated_decay_walk_can_still_need_the_placeholder(session):
    """Stopping the walk early makes the oldest surviving turn arbitrary. A full
    climb ends on the root, which is always a user message, so this only shows
    up once the cap has cut the chain."""
    conversation, question, _ = await a_deep_branch(session)

    context = await HierarchicalDecay().compose(
        await a_request(session, conversation, question, max_depth=1)
    )

    assert context.messages[0].role == "user"


def test_two_decay_strategies_with_the_same_tier_agree():
    """Frozen, and tuned only through its constructor, so one instance can serve
    every request the way the other three do."""
    assert HierarchicalDecay() == HierarchicalDecay(TieredDecay())
    assert HierarchicalDecay(TieredDecay(full_depth=1)) != HierarchicalDecay()


# --- across the strategies: what the experiment holds constant ------------


async def test_every_strategy_reports_its_own_name(session):
    conversation, question, _ = await a_branch(session)
    request = await a_request(session, conversation, question)

    for strategy in BUILT_STRATEGIES:
        context = await strategy.compose(request)

        assert context.strategy_used == strategy.name


async def test_every_strategy_shares_one_system_preamble(session):
    """A different preamble per strategy would be prompt wording showing up in
    the results as a context-composition win."""
    conversation, question, _ = await a_branch(session)
    request = await a_request(session, conversation, question)

    for strategy in BUILT_STRATEGIES:
        assert (await strategy.compose(request)).system == SYSTEM_PROMPT


async def test_every_strategy_ends_on_the_identical_question_turn(session):
    """The question and the highlight are held constant; only the ancestors
    vary. If this drifts, SpanOnly wins on branches for a reason that has
    nothing to do with how context was composed."""
    conversation, question, _ = await a_branch(session)
    request = await a_request(session, conversation, question)

    final_turns = [
        (await strategy.compose(request)).messages[-1]
        for strategy in BUILT_STRATEGIES
    ]

    assert len(set(final_turns)) == 1
    assert ANCHOR_TEXT in final_turns[0].content


async def test_the_strategies_differ_only_in_how_many_ancestors_they_send(session):
    conversation, question, ancestors = await a_branch(session)
    request = await a_request(session, conversation, question)

    counts = {
        strategy.name: len((await strategy.compose(request)).messages) - 1
        for strategy in BUILT_STRATEGIES
    }

    assert counts == {
        "FullInheritance": len(ancestors),
        "ParentOnly": 2,          # the parent plus the placeholder
        "SpanOnly": 0,
        # Same ancestors as full inheritance, deliberately. Decay differs in
        # how much of each one it sends, never in how many it sends.
        "HierarchicalDecay": len(ancestors),
    }


async def test_composing_twice_gives_the_same_prompt(session):
    """Each case is run several times and averaged, so any variation inside
    compose would land in that average looking like model variance."""
    conversation, question, _ = await a_branch(session)
    request = await a_request(session, conversation, question)

    first = await FullInheritance().compose(request)
    second = await FullInheritance().compose(request)

    assert first.messages == second.messages
