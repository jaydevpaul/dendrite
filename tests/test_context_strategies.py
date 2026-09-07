"""Context types, the strategy interface, and four of the five strategies.

These run against the real ancestor walk, not a hand-built one: the anchor a
strategy composes comes off the edge one level up, and that coupling is only
real if a real recursive query produced the step.

The cross-strategy tests at the bottom are the ones that matter most. The whole
project compares these strategies against each other, so anything that differs
between them for a reason *other* than which ancestors are sent will show up in
the results as a difference the experiment cannot explain.
"""

import asyncio
from dataclasses import dataclass

import pytest

from app.context.base import (
    EMBEDDING_MISSING,
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
    HierarchicalDecayWithRetrieval,
    ParentOnly,
    SpanOnly,
    SpanOnlyRequiresAnchor,
)
from app.llm.base import PromptMessage
from app.llm.fake import FakeLLMClient, fake_vector
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
    new_embedding,
    new_message,
    new_summary,
    new_user,
)

QUESTION_TEXT = "What does that cost me?"

SIMPLE_STRATEGIES = [FullInheritance(), ParentOnly(), SpanOnly()]

# Every arm that exists so far. The cross-strategy tests at the bottom run
# against this list, so a fifth arm joins it and immediately has to answer for
# the things all of them hold constant.
BUILT_STRATEGIES = [
    *SIMPLE_STRATEGIES,
    HierarchicalDecay(),
    HierarchicalDecayWithRetrieval(),
]


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


async def a_request(session, conversation, question, max_depth=200, llm=None):
    """What the composer will assemble: walk the chain, hand it to a strategy.

    Only the retrieval arm touches `llm` during composition, and only to embed
    the query - so the default client is fine everywhere else, and a test that
    wants a failing or slow embedder passes its own.
    """
    walk = await walk_ancestors(session, conversation, question.id, max_depth=max_depth)

    return StrategyRequest(
        session=session,
        llm=FakeLLMClient() if llm is None else llm,
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


# --- HierarchicalDecayWithRetrieval ---------------------------------------

# The four levels that fall outside the default tier, oldest first. Written so
# the ranking has a real answer rather than an arbitrary one: index 1 shares
# three words with the question and its highlight, index 3 shares one, and the
# other two share none. With four candidates a third rounds up to two, so
# indexes 1 and 3 are the two that should come back full.
OLDER_TEXTS = [
    "HNSW builds a navigable small world graph over the vectors.",
    "Recall and speed trade against each other in every vector index.",
    "Autovacuum on a write-heavy table needs its own settings.",
    "Latency and speed are not the same measurement.",
]

NEWER_TEXTS = [
    "The deployment pipeline runs on a self-hosted runner.",
    "Continuous integration caches the wheel build between jobs.",
]


@dataclass
class SlowEmbedClient(FakeLLMClient):
    """An embedder that takes its time. Nothing else about the fake changes -
    generation still works, because a slow embedding service is not a broken
    model."""

    embed_delay: float = 0.0

    async def embed(self, text: str) -> list[float]:
        self.embed_calls.append(text)
        await asyncio.sleep(self.embed_delay)
        return fake_vector(text)


async def a_retrieval_branch(
    session, summarised="older", embedded="older", anchor=SPAN
):
    """A seven-ancestor branch whose older levels have distinguishable text.

    `a_deep_branch` names its levels m0 to m5, which is fine for counting turns
    and useless for ranking them - every candidate would be equally far from the
    question and the winner would be whichever one the plan emitted first. These
    six carry real sentences instead, so "the nearest two" is a fact about the
    text rather than an accident.

    Depths run 1 to 7, so the newest three are full under the default tier and
    `ancestors[:4]` are the summarized ones - which are also the candidates.
    """
    user = await new_user(session)
    conversation = await new_conversation(session, user)

    trunk = []
    for index, text in enumerate([*OLDER_TEXTS, *NEWER_TEXTS]):
        role = "assistant" if index % 2 else "user"
        message = await new_message(session, conversation, role, text)
        if trunk:
            await link(session, trunk[-1], message)
        trunk.append(message)

    reply = await new_message(session, conversation, "assistant", PARENT_TEXT)
    await link(session, trunk[-1], reply)

    question = await new_message(session, conversation, "user", QUESTION_TEXT)
    await link(session, reply, question, anchor=anchor)

    ancestors = [*trunk, reply]
    older = ancestors[:4]

    for ancestor in {"older": older, "none": [], "all": ancestors}[summarised]:
        await new_summary(
            session, ancestor, summary_text=f"a summary of {ancestor.content}"
        )

    for ancestor in {"older": older, "none": []}[embedded]:
        await new_embedding(session, ancestor)

    await session.commit()
    return conversation, question, ancestors


async def test_retrieval_promotes_the_nearest_summarised_levels(session):
    """Two of the four summarized levels come back in full, and they are the two
    whose text actually relates to what was asked."""
    conversation, question, ancestors = await a_retrieval_branch(session)

    context = await HierarchicalDecayWithRetrieval().compose(
        await a_request(session, conversation, question)
    )

    assert [turn.content for turn in context.messages[:4]] == [
        f"{SUMMARY_MARKER} a summary of {ancestors[0].content}",
        ancestors[1].content,
        f"{SUMMARY_MARKER} a summary of {ancestors[2].content}",
        ancestors[3].content,
    ]


async def test_a_promoted_level_stays_where_it_was(session):
    """In place, not appended as a block of relevant excerpts at the end.
    Appending would send the promoted message twice - once shortened in
    position and again in full out of order - and the metric is quality per
    token, so paying twice for one message is measured directly."""
    conversation, question, ancestors = await a_retrieval_branch(session)
    request = await a_request(session, conversation, question)

    retrieved = await HierarchicalDecayWithRetrieval().compose(request)
    decayed = await HierarchicalDecay().compose(request)

    assert len(retrieved.messages) == len(decayed.messages)
    assert len(retrieved.messages) == len(ancestors) + 1
    assert [turn.role for turn in retrieved.messages] == [
        turn.role for turn in decayed.messages
    ]


async def test_retrieval_cannot_undo_the_full_fidelity_tier(session):
    """It only ever looks at levels decay marked for summarizing, so the nearest
    three are not candidates and cannot be affected by what the ranking says."""
    conversation, question, ancestors = await a_retrieval_branch(session)

    context = await HierarchicalDecayWithRetrieval().compose(
        await a_request(session, conversation, question)
    )

    assert [turn.content for turn in context.messages[-4:-1]] == [
        ancestor.content for ancestor in ancestors[-3:]
    ]


async def test_two_thirds_of_the_summaries_survive_promotion(session):
    """Four candidates, so two stay summarized. Promoting all of them would make
    this arm byte-identical to full inheritance, and the comparison would be
    reporting five arms while running four."""
    conversation, question, _ = await a_retrieval_branch(session)

    context = await HierarchicalDecayWithRetrieval().compose(
        await a_request(session, conversation, question)
    )

    assert len(summarised_turns(context)) == 2


async def test_a_chain_inside_the_tier_retrieves_nothing(session, engine):
    """Three ancestors, all sent in full, so there is nothing that could be
    promoted. No embedding call and no query - the embedding call is the one
    piece of network in the whole composition, and this is a request that would
    pay for it and get nothing."""
    conversation, question, ancestors = await a_branch(session, trunk_length=2)
    llm = FakeLLMClient()
    request = await a_request(session, conversation, question, llm=llm)

    with counting_queries(engine) as sent:
        context = await HierarchicalDecayWithRetrieval().compose(request)

    assert sent == []
    assert llm.embed_calls == []
    assert context.degradations == []
    assert [turn.content for turn in context.messages[:-1]] == [
        ancestor.content for ancestor in ancestors
    ]


async def test_the_query_is_the_question_and_the_highlight(session):
    """What the user asked, plus the passage they highlighted. The highlight is
    what the branch is about, and on a short question it carries most of the
    meaning there is to match on."""
    conversation, question, _ = await a_retrieval_branch(session)
    llm = FakeLLMClient()

    await HierarchicalDecayWithRetrieval().compose(
        await a_request(session, conversation, question, llm=llm)
    )

    assert len(llm.embed_calls) == 1
    assert QUESTION_TEXT in llm.embed_calls[0]
    assert ANCHOR_TEXT in llm.embed_calls[0]


async def test_a_continuation_queries_on_the_question_alone(session):
    """A continuation has no highlight, and that is ordinary rather than an
    error - there is simply less to match on."""
    conversation, question, _ = await a_retrieval_branch(session, anchor=None)
    llm = FakeLLMClient()

    await HierarchicalDecayWithRetrieval().compose(
        await a_request(session, conversation, question, llm=llm)
    )

    assert llm.embed_calls == [QUESTION_TEXT]


# --- when the embeddings are not there ------------------------------------


async def test_a_candidate_with_no_embedding_is_reported(session):
    """Nothing populates the embedding table yet, and the honest record of that
    is a degradation rather than silence: retrieval ran, named itself, and
    produced a prompt identical to plain decay's."""
    conversation, question, ancestors = await a_retrieval_branch(
        session, embedded="none"
    )
    await new_embedding(session, ancestors[1])
    await session.commit()

    context = await HierarchicalDecayWithRetrieval().compose(
        await a_request(session, conversation, question)
    )

    assert context.degradations == [EMBEDDING_MISSING]
    assert context.strategy_used == "HierarchicalDecayWithRetrieval"


async def test_partial_coverage_still_promotes_what_it_found(session):
    """Three of four embedded is not a reason to throw the ranking away.
    Retrieval genuinely ran, and falling back to plain decay here would discard
    real work over a level the embedder has not reached yet."""
    conversation, question, ancestors = await a_retrieval_branch(
        session, embedded="none"
    )
    for ancestor in ancestors[1:4]:
        await new_embedding(session, ancestor)
    await session.commit()

    context = await HierarchicalDecayWithRetrieval().compose(
        await a_request(session, conversation, question)
    )

    assert context.degradations == [EMBEDDING_MISSING]
    assert [turn.content for turn in context.messages[:4]] == [
        f"{SUMMARY_MARKER} a summary of {ancestors[0].content}",
        ancestors[1].content,
        f"{SUMMARY_MARKER} a summary of {ancestors[2].content}",
        ancestors[3].content,
    ]


async def test_a_fully_embedded_chain_reports_nothing(session):
    conversation, question, _ = await a_retrieval_branch(session)

    context = await HierarchicalDecayWithRetrieval().compose(
        await a_request(session, conversation, question)
    )

    assert context.degradations == []


async def test_the_missing_embedding_has_its_own_name(session):
    """A summariser backlog and an embedder backlog are different jobs with
    different fixes, and plain decay can report the first one too - so sharing
    a name would leave this arm's rate unable to say which was behind it."""
    assert EMBEDDING_MISSING != SUMMARY_MISSING


async def test_nothing_summarised_means_nothing_to_promote(session):
    """Every level marked for a summary went out in full instead, so there is
    nothing left for retrieval to promote and it does not go looking. The
    summariser backlog is already reported, which is the finding here."""
    conversation, question, _ = await a_retrieval_branch(
        session, summarised="none", embedded="none"
    )
    llm = FakeLLMClient()

    context = await HierarchicalDecayWithRetrieval().compose(
        await a_request(session, conversation, question, llm=llm)
    )

    assert llm.embed_calls == []
    assert context.degradations == [SUMMARY_MISSING]
    assert context.strategy_used == "HierarchicalDecayWithRetrieval"


async def test_a_level_with_no_summary_is_not_a_candidate(session):
    """It is already being sent in full, so promoting it would buy nothing while
    using up one of the two promotion slots."""
    conversation, question, ancestors = await a_retrieval_branch(
        session, summarised="none", embedded="older"
    )
    for ancestor in ancestors[:2]:
        await new_summary(
            session, ancestor, summary_text=f"a summary of {ancestor.content}"
        )
    await session.commit()

    context = await HierarchicalDecayWithRetrieval().compose(
        await a_request(session, conversation, question)
    )

    # Two candidates now, so a third rounds up to one promotion - and it goes to
    # the one of the two that the question is actually about.
    assert [turn.content for turn in context.messages[:4]] == [
        f"{SUMMARY_MARKER} a summary of {ancestors[0].content}",
        ancestors[1].content,
        ancestors[2].content,
        ancestors[3].content,
    ]
    assert context.degradations == [SUMMARY_MISSING]


# --- when the embedding service is down -----------------------------------


async def test_a_failed_embedding_falls_back_to_plain_decay(session):
    """The one network call inside composition, so this is where the fallback
    lives. What gets recorded is plain decay, because plain decay is what
    actually ran - and comparing that against the arm the harness asked for is
    how a degraded run is spotted afterwards."""
    conversation, question, _ = await a_retrieval_branch(session)
    llm = FakeLLMClient(fail_on_embed=True)

    context = await HierarchicalDecayWithRetrieval().compose(
        await a_request(session, conversation, question, llm=llm)
    )

    assert context.strategy_used == "HierarchicalDecay"
    assert context.degradations == []
    assert len(summarised_turns(context)) == 4


async def test_a_slow_embedding_falls_back_the_same_way(session):
    """Composition has a second or two before the first token, so an embedding
    service that is up but not answering has to be treated as one that is down.
    Waiting for it would spend the whole budget on the optional half."""
    conversation, question, _ = await a_retrieval_branch(session)
    llm = SlowEmbedClient(embed_delay=0.5)

    context = await HierarchicalDecayWithRetrieval(timeout_seconds=0.01).compose(
        await a_request(session, conversation, question, llm=llm)
    )

    assert context.strategy_used == "HierarchicalDecay"
    assert context.degradations == []


async def test_a_failed_embedding_skips_the_ranking_query(session, engine):
    """No vector, nothing to rank. The summaries were already read, so the
    fallback costs the one query plain decay would have cost anyway."""
    conversation, question, _ = await a_retrieval_branch(session)
    llm = FakeLLMClient(fail_on_embed=True)
    request = await a_request(session, conversation, question, llm=llm)

    with counting_queries(engine) as sent:
        await HierarchicalDecayWithRetrieval().compose(request)

    assert len(sent) == 1


async def test_a_fallback_still_reports_the_summariser_backlog(session):
    """The embedding failure is recorded by the strategy name rather than by a
    degradation, so the other findings still have to come through. Three levels
    have summaries and one does not, so the embed call happens, fails, and the
    missing summary is reported anyway."""
    conversation, question, ancestors = await a_retrieval_branch(
        session, summarised="none", embedded="none"
    )
    for ancestor in ancestors[:3]:
        await new_summary(
            session, ancestor, summary_text=f"a summary of {ancestor.content}"
        )
    await session.commit()
    llm = FakeLLMClient(fail_on_embed=True)

    context = await HierarchicalDecayWithRetrieval().compose(
        await a_request(session, conversation, question, llm=llm)
    )

    assert llm.embed_calls != []
    assert context.strategy_used == "HierarchicalDecay"
    assert context.degradations == [SUMMARY_MISSING]


# --- cost, tuning and shape -----------------------------------------------


async def test_the_whole_chain_costs_two_queries_and_one_embedding(session, engine):
    """One read for the summaries and one for the ranking, plus the single
    embedding call. Anything per-level here would be a round trip per ancestor
    while the user waits for the first token."""
    conversation, question, _ = await a_retrieval_branch(session)
    llm = FakeLLMClient()
    request = await a_request(session, conversation, question, llm=llm)

    with counting_queries(engine) as sent:
        await HierarchicalDecayWithRetrieval().compose(request)

    assert len(sent) == 2
    assert len(llm.embed_calls) == 1


async def test_the_fraction_is_tunable(session):
    """Both knobs are constructor arguments so the evaluation can sweep them."""
    conversation, question, _ = await a_retrieval_branch(session)
    request = await a_request(session, conversation, question)

    generous = await HierarchicalDecayWithRetrieval(fraction=1.0).compose(request)
    default = await HierarchicalDecayWithRetrieval().compose(request)

    assert len(summarised_turns(generous)) == 0
    assert len(summarised_turns(default)) == 2


async def test_the_promotion_cap_is_tunable(session):
    conversation, question, _ = await a_retrieval_branch(session)
    request = await a_request(session, conversation, question)

    capped = await HierarchicalDecayWithRetrieval(
        fraction=1.0, max_promotions=1
    ).compose(request)

    assert len(summarised_turns(capped)) == 3


async def test_the_decay_function_is_swappable_here_too(session):
    """Declared before the name, so the positional form sets the tier. The other
    way round it would land in `name` with nothing raising, and the wrong string
    would surface much later in the recorded strategy."""
    conversation, question, ancestors = await a_retrieval_branch(
        session, summarised="all", embedded="none"
    )

    shallow = HierarchicalDecayWithRetrieval(TieredDecay(full_depth=1))

    assert shallow.decay == TieredDecay(full_depth=1)
    assert shallow.name == "HierarchicalDecayWithRetrieval"

    context = await shallow.compose(await a_request(session, conversation, question))

    # Six levels marked for a summary, a third of them promoted - except that
    # none of them are embedded, so all six stay summarized.
    assert len(summarised_turns(context)) == len(ancestors) - 1


async def test_it_reports_a_truncated_walk(session):
    """This arm climbs to the root, so a walk that stopped short really did cut
    what it sent."""
    conversation, question, _ = await a_retrieval_branch(session)

    context = await HierarchicalDecayWithRetrieval().compose(
        await a_request(session, conversation, question, max_depth=3)
    )

    assert WALK_TRUNCATED in context.degradations


async def test_all_three_degradations_can_fire_at_once(session):
    """A walk cut short, a level with no summary and a candidate with no vector
    are three separate findings with three separate fixes, so all three are
    recorded rather than one standing in for the others."""
    conversation, question, ancestors = await a_retrieval_branch(
        session, summarised="none", embedded="none"
    )
    await new_summary(session, ancestors[3], summary_text="the fourth, shortened")
    await new_summary(session, ancestors[2], summary_text="the third, shortened")
    await new_embedding(session, ancestors[3])
    await session.commit()

    context = await HierarchicalDecayWithRetrieval().compose(
        await a_request(session, conversation, question, max_depth=6)
    )

    assert context.degradations == [WALK_TRUNCATED, SUMMARY_MISSING, EMBEDDING_MISSING]


async def test_composing_twice_gives_the_same_prompt(session):
    """The ranking has to be a function of the data, not of the plan. Each
    scenario is run several times and averaged, so variation here would land in
    that average looking like model variance."""
    conversation, question, _ = await a_retrieval_branch(session)
    request = await a_request(session, conversation, question)

    first = await HierarchicalDecayWithRetrieval().compose(request)
    second = await HierarchicalDecayWithRetrieval().compose(request)

    assert first.messages == second.messages


def test_two_retrieval_strategies_with_the_same_settings_agree():
    assert HierarchicalDecayWithRetrieval() == HierarchicalDecayWithRetrieval(
        TieredDecay()
    )
    assert HierarchicalDecayWithRetrieval(fraction=0.5) != (
        HierarchicalDecayWithRetrieval()
    )


def test_the_tuning_arguments_are_validated():
    """A fraction of zero promotes nothing and quietly turns this arm into the
    one next to it in the comparison."""
    with pytest.raises(ValueError):
        HierarchicalDecayWithRetrieval(fraction=0)

    with pytest.raises(ValueError):
        HierarchicalDecayWithRetrieval(fraction=1.5)

    with pytest.raises(ValueError):
        HierarchicalDecayWithRetrieval(max_promotions=0)

    with pytest.raises(ValueError):
        HierarchicalDecayWithRetrieval(timeout_seconds=0)


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
        # And retrieval changes which of them are sent in full, never how many
        # turns there are - the whole point of promoting in place.
        "HierarchicalDecayWithRetrieval": len(ancestors),
    }


async def test_composing_twice_gives_the_same_prompt(session):
    """Each case is run several times and averaged, so any variation inside
    compose would land in that average looking like model variance."""
    conversation, question, _ = await a_branch(session)
    request = await a_request(session, conversation, question)

    first = await FullInheritance().compose(request)
    second = await FullInheritance().compose(request)

    assert first.messages == second.messages
