"""The decay function, the summary reader, and how a summarized turn renders.

These are the two halves HierarchicalDecay will bolt together next: a rule that
decides *which* ancestors drop to summaries, and a reader that fetches the
summaries those ancestors have. They are tested apart because they fail apart -
a wrong tier sends the right text at the wrong level, a wrong read sends the
wrong text at the right one.

The decay tests use hand-made steps rather than a real walk. That is deliberate:
the tier reads a step's depth and nothing else, so a test that had to build a
graph to check it would be testing the walk again.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.context.base import (
    SUMMARY_MARKER,
    SUMMARY_MISSING,
    SYSTEM_PROMPT,
    WALK_TRUNCATED,
    full_turn,
    summarised_turn,
)
from app.context.decay import TieredDecay
from app.services.ancestors import AncestorStep
from app.services.summary import load_summaries
from tests.conftest import counting_queries
from tests.graph_builders import (
    new_conversation,
    new_message,
    new_summary,
    new_user,
)


def steps_down_to(depth):
    """Steps 1..depth, nearest first, carrying nothing but their depth.

    A tier that looked at message content or at an edge could not pass this,
    which is the point - the depth tier is the implementation that deliberately
    ignores both, so that what gets composed does not vary with how long the
    conversation's messages happen to be.
    """
    return [AncestorStep(depth=d, message=None, edge=None) for d in range(1, depth + 1)]


# --- the tier -------------------------------------------------------------


def test_the_default_tier_keeps_three_levels_full():
    """Span, parent, and one more - then summaries. This number lives in one
    place, and this is that place."""
    fidelities = TieredDecay().assign(steps_down_to(6))

    assert fidelities == ["full", "full", "full", "summary", "summary", "summary"]


def test_there_is_one_fidelity_per_step_in_the_same_order():
    steps = steps_down_to(5)

    fidelities = TieredDecay().assign(steps)

    assert len(fidelities) == len(steps)


def test_nothing_is_ever_dropped():
    """Summarized, never removed. If decay covered fewer ancestors than full
    inheritance, a token saving could not be attributed to summarization -
    decay would simply have sent less of the conversation."""
    fidelities = TieredDecay().assign(steps_down_to(40))

    assert len(fidelities) == 40
    assert set(fidelities) <= {"full", "summary"}


def test_a_chain_shorter_than_the_tier_is_entirely_full():
    assert TieredDecay().assign(steps_down_to(2)) == ["full", "full"]


def test_no_steps_gives_no_fidelities():
    """The question is the first message in the conversation: nothing above it."""
    assert TieredDecay().assign([]) == []


def test_the_tier_depth_is_swappable():
    fidelities = TieredDecay(full_depth=1).assign(steps_down_to(3))

    assert fidelities == ["full", "summary", "summary"]


def test_a_tier_of_zero_summarises_everything():
    assert TieredDecay(full_depth=0).assign(steps_down_to(2)) == ["summary", "summary"]


def test_a_negative_tier_is_rejected():
    with pytest.raises(ValueError):
        TieredDecay(full_depth=-1)


def test_it_reads_the_depth_and_not_the_position():
    """The walk comes back nearest-first and a prompt reads oldest-first, so
    both orders are in circulation. Answering by list position instead of by
    depth would give a reversed chain a reversed answer."""
    steps = steps_down_to(5)

    forwards = TieredDecay().assign(steps)
    backwards = TieredDecay().assign(list(reversed(steps)))

    assert backwards == list(reversed(forwards))


def test_two_decays_with_the_same_tier_agree():
    """Frozen and argument-free apart from tuning, so one instance can serve
    every request."""
    assert TieredDecay(full_depth=2) == TieredDecay(full_depth=2)


# --- the reader -----------------------------------------------------------


async def a_conversation_with_messages(session, count=3):
    user = await new_user(session)
    conversation = await new_conversation(session, user)
    messages = [
        await new_message(session, conversation, content=f"m{i}") for i in range(count)
    ]
    return conversation, messages


async def test_it_returns_a_summary_for_every_message_that_has_one(session):
    _, messages = await a_conversation_with_messages(session)
    for i, message in enumerate(messages):
        await new_summary(session, message, summary_text=f"summary {i}")

    summaries = await load_summaries(session, [m.id for m in messages])

    assert summaries == {m.id: f"summary {i}" for i, m in enumerate(messages)}


async def test_a_message_with_no_summary_is_absent_rather_than_empty(session):
    """Summarization runs in the background after a message is written, so a
    recent ancestor having no row yet is the normal state, not a fault. The
    caller sends its full text - costlier, still correct - and an absent key
    says that plainly where a None or an empty string would have to be
    distinguished from a summary that really is blank."""
    _, messages = await a_conversation_with_messages(session, count=2)
    await new_summary(session, messages[0], summary_text="only this one")

    summaries = await load_summaries(session, [m.id for m in messages])

    assert summaries == {messages[0].id: "only this one"}
    assert messages[1].id not in summaries


async def test_the_most_recent_summary_wins(session):
    _, messages = await a_conversation_with_messages(session, count=1)
    message = messages[0]
    now = datetime.now(timezone.utc)

    await new_summary(
        session, message, summary_text="stale", created_at=now - timedelta(days=1)
    )
    await new_summary(session, message, summary_text="current", created_at=now)

    summaries = await load_summaries(session, [message.id])

    assert summaries == {message.id: "current"}


async def test_the_later_id_breaks_a_timestamp_tie(session):
    """created_at defaults to now(), which is *transaction* time - so two
    summaries written in one transaction carry the same timestamp and the
    newest is not recoverable from it. UUIDv7 sorts by creation, so the larger
    id is genuinely the later row, and that is what settles it."""
    _, messages = await a_conversation_with_messages(session, count=1)
    message = messages[0]

    first = await new_summary(session, message, summary_text="written first")
    second = await new_summary(session, message, summary_text="written second")

    summaries = await load_summaries(session, [message.id])

    assert second.id > first.id
    assert summaries == {message.id: "written second"}


async def test_a_blank_summary_reads_as_missing(session):
    """A summary with no text in it is not a cheaper version of the message -
    it is the message gone. Sending the marker with nothing after it would drop
    that ancestor while the strategy still counted it as covered, which is
    exactly the coverage-for-fidelity trade the decay arms are built to avoid.
    An absent key sends the full text instead."""
    _, messages = await a_conversation_with_messages(session, count=1)
    message = messages[0]
    await new_summary(session, message, summary_text="")

    summaries = await load_summaries(session, [message.id])

    assert summaries == {}


async def test_a_whitespace_only_summary_reads_as_missing(session):
    """Same thing with the emptiness harder to see. A summariser that returns a
    stray newline has produced nothing, and the check is on the trimmed text so
    that it says so."""
    _, messages = await a_conversation_with_messages(session, count=1)
    message = messages[0]
    await new_summary(session, message, summary_text="  \n  ")

    summaries = await load_summaries(session, [message.id])

    assert summaries == {}


async def test_a_blank_summary_does_not_beat_a_real_older_one(session):
    """Why blank rows are excluded in the query rather than dropped from the
    map afterwards. Only the most recent summary per message survives the
    query, so a blank one written today would win on recency and then be thrown
    away - taking a perfectly good older summary with it, and costing full text
    for a message that had one. Excluded up front, the blank never competes."""
    _, messages = await a_conversation_with_messages(session, count=1)
    message = messages[0]

    await new_summary(session, message, summary_text="a real summary")
    await new_summary(session, message, summary_text="")

    summaries = await load_summaries(session, [message.id])

    assert summaries == {message.id: "a real summary"}


async def test_only_the_requested_messages_come_back(session):
    """Composition asks about one chain. A sibling branch's summaries are
    exactly the context the user branched away from."""
    _, messages = await a_conversation_with_messages(session, count=2)
    asked_about, elsewhere = messages
    await new_summary(session, asked_about, summary_text="in the chain")
    await new_summary(session, elsewhere, summary_text="off the chain")

    summaries = await load_summaries(session, [asked_about.id])

    assert summaries == {asked_about.id: "in the chain"}


async def test_no_ids_asks_the_database_nothing(session, engine):
    with counting_queries(engine) as sent:
        summaries = await load_summaries(session, [])

    assert summaries == {}
    assert sent == []


async def test_the_whole_chain_costs_one_query(session, engine):
    """The reader takes ids and returns a map for exactly this reason. Fetching
    per ancestor inside the composition loop would be a round trip per level,
    and composition has one to two seconds to do everything in."""
    _, messages = await a_conversation_with_messages(session, count=8)
    for message in messages:
        await new_summary(session, message)

    with counting_queries(engine) as sent:
        summaries = await load_summaries(session, [m.id for m in messages])

    assert len(summaries) == 8
    assert len(sent) == 1


async def test_the_model_filter_is_off_by_default(session):
    """Nothing writes summaries yet and no summariser model is configured, so
    a filter would have nothing to filter on today. Off by default keeps the
    reader honest about that instead of pretending to a precision it has not
    got."""
    _, messages = await a_conversation_with_messages(session, count=1)
    message = messages[0]

    await new_summary(session, message, summary_text="older model", model_used="v1")
    await new_summary(session, message, summary_text="newer model", model_used="v2")

    summaries = await load_summaries(session, [message.id])

    assert summaries == {message.id: "newer model"}


async def test_the_model_filter_pins_the_summariser(session):
    """Two summarisers' output mixes silently otherwise. If a message were
    re-summarised by a better model partway through an eval run, the decay arms
    would quietly start sending better summaries - and the summariser upgrade
    would then read as a context-composition win in the results. Having the
    parameter now is what makes switching it on a one-line change at the call
    site later, rather than a rewrite of this function and its tests."""
    _, messages = await a_conversation_with_messages(session, count=1)
    message = messages[0]

    await new_summary(session, message, summary_text="older model", model_used="v1")
    await new_summary(session, message, summary_text="newer model", model_used="v2")

    summaries = await load_summaries(session, [message.id], model="v1")

    assert summaries == {message.id: "older model"}


async def test_a_pinned_model_with_no_summaries_reads_as_missing(session):
    """The same absent key as a message that was never summarised, and the same
    consequence - the caller sends full text. A pinned model the summariser has
    not caught up to is not an error."""
    _, messages = await a_conversation_with_messages(session, count=1)
    message = messages[0]
    await new_summary(session, message, model_used="v1")

    summaries = await load_summaries(session, [message.id], model="v2")

    assert summaries == {}


async def test_the_model_filter_still_takes_the_most_recent(session):
    """The filter narrows which rows are candidates. It does not change how the
    winner is chosen among them."""
    _, messages = await a_conversation_with_messages(session, count=1)
    message = messages[0]

    await new_summary(session, message, summary_text="stale v1", model_used="v1")
    await new_summary(session, message, summary_text="current v1", model_used="v1")
    await new_summary(session, message, summary_text="a v2 summary", model_used="v2")

    summaries = await load_summaries(session, [message.id], model="v1")

    assert summaries == {message.id: "current v1"}


# --- how a summarized ancestor renders ------------------------------------


async def test_a_summarised_turn_keeps_its_original_role(session):
    """A summary of what a participant said is still that participant's turn.
    Moving it to a system or user voice would invent a speaker who never
    spoke."""
    conversation, _ = await a_conversation_with_messages(session, count=1)
    reply = await new_message(session, conversation, "assistant", "a reply")

    turn = summarised_turn(reply, "the short version")

    assert turn.role == "assistant"


async def test_a_summarised_turn_is_marked_where_the_preamble_says_to_look(session):
    """The system preamble tells the model that a turn beginning with the
    marker is a summary rather than someone's words. If the two ever disagree
    the model reads a paraphrase as a quotation."""
    _, messages = await a_conversation_with_messages(session, count=1)

    turn = summarised_turn(messages[0], "the short version")

    assert turn.content.startswith(SUMMARY_MARKER)
    assert SUMMARY_MARKER in SYSTEM_PROMPT


async def test_the_summary_text_survives_the_marker(session):
    _, messages = await a_conversation_with_messages(session, count=1)

    turn = summarised_turn(messages[0], "the short version")

    assert turn.content == f"{SUMMARY_MARKER} the short version"


async def test_a_summarised_turn_differs_from_a_full_one_only_in_content(session):
    _, messages = await a_conversation_with_messages(session, count=1)

    full = full_turn(messages[0])
    summarised = summarised_turn(messages[0], "the short version")

    assert summarised.role == full.role
    assert summarised.content != full.content


def test_the_missing_summary_degradation_has_a_name_of_its_own():
    """Falling back to full text and hitting the walk cap are different
    degradations with different costs, and the eval reports a rate per name -
    one standing in for the other would merge two findings into one."""
    assert SUMMARY_MISSING != WALK_TRUNCATED
