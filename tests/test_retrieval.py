"""Ancestor-scoped vector retrieval, and the rule for how many get promoted.

Two separate things live here. `promotion_count` is arithmetic with no database
in it, so it is tested directly. The query is the other half, and what it is
mostly tested for is what it must *not* return: a sibling branch, a vector from
another embedding model, or the same message twice.

Isolation in this table is a property of the query rather than of the schema -
every embedding in the system shares one table - so a forgotten filter here does
not fail, it quietly widens the search.
"""

from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.llm.fake import fake_vector
from app.services.retrieval import promotion_count, rank_ancestors_by_similarity
from tests.conftest import counting_queries
from tests.graph_builders import (
    chain_of,
    new_conversation,
    new_embedding,
    new_message,
    new_user,
)

QUERY_TEXT = "recall and speed"

# Distances against QUERY_TEXT under the fake embedder, nearest first. Written
# as prose the fixtures embed rather than as vectors, because prose is what the
# real embedder will be handed.
NEAR = "recall and speed"
MIDDLE = "recall traded against something else entirely"
FAR = "autovacuum on a write-heavy table"


async def three_candidates(session):
    """Three messages in one conversation, returned oldest first."""
    user = await new_user(session)
    conversation = await new_conversation(session, user)
    messages = await chain_of(session, conversation, 3)
    return conversation, messages


# --- how many get promoted ------------------------------------------------


def test_a_third_of_the_summarised_levels_are_promoted():
    """A fraction rather than a fixed k. With a fixed k of ten, every chain
    shallower than about a dozen levels would have all of its summaries
    promoted, and this arm would send exactly what full inheritance sends -
    two of the five arms measuring the same thing."""
    assert promotion_count(9, fraction=1 / 3, max_promotions=10) == 3


def test_two_thirds_of_the_summaries_always_survive():
    """Whatever the chain length, most of the saving is kept. That is what stops
    the arm collapsing into full inheritance on a long conversation."""
    for n_candidates in range(1, 60):
        promoted = promotion_count(n_candidates, fraction=1 / 3, max_promotions=10)

        assert promoted <= n_candidates
        assert promoted <= -(-n_candidates // 3)


def test_a_short_chain_promotes_one_rather_than_none():
    """Rounding up, so an arm with one or two summarized levels still retrieves
    something. Rounding down it would promote nobody and silently be plain
    decay, which is the arm next to it in the comparison."""
    assert promotion_count(1, fraction=1 / 3, max_promotions=10) == 1
    assert promotion_count(2, fraction=1 / 3, max_promotions=10) == 1


def test_the_ceiling_caps_a_runaway_chain():
    """A walk can reach two hundred levels, where a third would be sixty-six
    full messages. This is a guard against that, not a working setting."""
    assert promotion_count(200, fraction=1 / 3, max_promotions=10) == 10


def test_nothing_summarised_promotes_nothing():
    assert promotion_count(0, fraction=1 / 3, max_promotions=10) == 0


def test_the_fraction_is_tunable():
    """Both numbers are constructor arguments so the evaluation can sweep them,
    which only means anything if they actually move the answer."""
    assert promotion_count(9, fraction=1.0, max_promotions=10) == 9
    assert promotion_count(9, fraction=0.1, max_promotions=10) == 1


# --- the query ------------------------------------------------------------


async def test_candidates_come_back_nearest_first(session):
    _, messages = await three_candidates(session)
    await new_embedding(session, messages[0], text=FAR)
    await new_embedding(session, messages[1], text=NEAR)
    await new_embedding(session, messages[2], text=MIDDLE)
    await session.commit()

    ranked = await rank_ancestors_by_similarity(
        session,
        [message.id for message in messages],
        fake_vector(QUERY_TEXT),
        settings.embedding_model,
    )

    assert ranked == [messages[1].id, messages[2].id, messages[0].id]


async def test_a_candidate_with_no_embedding_is_simply_absent(session):
    """Nothing has embedded anything yet, so a candidate with no row is the
    ordinary state rather than a fault. The caller counts what came back to
    decide whether that is worth reporting."""
    _, messages = await three_candidates(session)
    await new_embedding(session, messages[1], text=NEAR)
    await session.commit()

    ranked = await rank_ancestors_by_similarity(
        session,
        [message.id for message in messages],
        fake_vector(QUERY_TEXT),
        settings.embedding_model,
    )

    assert ranked == [messages[1].id]


async def test_a_message_outside_the_candidate_list_is_never_returned(session):
    """The candidates are the ancestors of this question. Anything else in the
    table is a sibling branch or another conversation - and a sibling branch is
    precisely the context the user branched away from, so reaching it would be
    worse than useless."""
    conversation, messages = await three_candidates(session)
    outsider = await new_message(session, conversation, "user", "a sibling")
    await new_embedding(session, outsider, text=NEAR)
    await new_embedding(session, messages[0], text=FAR)
    await session.commit()

    ranked = await rank_ancestors_by_similarity(
        session,
        [messages[0].id],
        fake_vector(QUERY_TEXT),
        settings.embedding_model,
    )

    assert ranked == [messages[0].id]


async def test_a_vector_from_another_model_is_invisible(session):
    """Two embedding models put the same sentence in two unrelated spaces, so a
    distance computed across them is a number with no meaning. Filtering keeps
    the comparison honest - and the failure without it is a plausible-looking
    ranking rather than an error."""
    _, messages = await three_candidates(session)
    await new_embedding(session, messages[0], text=NEAR, model_used="some-other-model")
    await new_embedding(session, messages[1], text=FAR)
    await session.commit()

    ranked = await rank_ancestors_by_similarity(
        session,
        [message.id for message in messages],
        fake_vector(QUERY_TEXT),
        settings.embedding_model,
    )

    assert ranked == [messages[1].id]


async def test_a_re_embedded_message_uses_its_newest_vector(session):
    """Nothing stops a message being embedded twice, so the reader picks the
    current one the same way the summary reader does. Here the newest vector is
    the far one, so the message it belongs to must lose."""
    _, messages = await three_candidates(session)
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    await new_embedding(session, messages[0], text=NEAR, created_at=yesterday)
    await new_embedding(session, messages[0], text=FAR)
    await new_embedding(session, messages[1], text=MIDDLE)
    await session.commit()

    ranked = await rank_ancestors_by_similarity(
        session,
        [message.id for message in messages],
        fake_vector(QUERY_TEXT),
        settings.embedding_model,
    )

    assert ranked == [messages[1].id, messages[0].id]


async def test_a_re_embedded_message_takes_only_one_place(session):
    """Two rows for one message would otherwise occupy two of the promotion
    slots, so the arm would promote fewer distinct ancestors than it thinks."""
    _, messages = await three_candidates(session)
    await new_embedding(session, messages[0], text=NEAR)
    await new_embedding(session, messages[0], text=NEAR)
    await session.commit()

    ranked = await rank_ancestors_by_similarity(
        session,
        [message.id for message in messages],
        fake_vector(QUERY_TEXT),
        settings.embedding_model,
    )

    assert ranked == [messages[0].id]


async def test_an_exact_tie_goes_to_the_nearer_ancestor(session):
    """Two candidates can be equally close - identical text, or text the
    embedder finds no words in at all. Left to the database the winner would
    vary between runs, so the tie falls back to recency, which is the bias the
    decay tier already encodes."""
    _, messages = await three_candidates(session)
    await new_embedding(session, messages[0], text=NEAR)
    await new_embedding(session, messages[2], text=NEAR)
    await session.commit()

    nearest_first = [messages[2].id, messages[0].id]

    ranked = await rank_ancestors_by_similarity(
        session, nearest_first, fake_vector(QUERY_TEXT), settings.embedding_model
    )

    assert ranked == nearest_first

    # The same two rows asked for in the other order: the caller's order
    # decides, not whatever the query plan happens to emit.
    reversed_ranked = await rank_ancestors_by_similarity(
        session,
        list(reversed(nearest_first)),
        fake_vector(QUERY_TEXT),
        settings.embedding_model,
    )

    assert reversed_ranked == list(reversed(nearest_first))


async def test_no_candidates_asks_the_database_nothing(session, engine):
    """A chain short enough that nothing was summarized has nothing to promote.
    A query here is one the user waits for and gets nothing from."""
    with counting_queries(engine) as sent:
        ranked = await rank_ancestors_by_similarity(
            session, [], fake_vector(QUERY_TEXT), settings.embedding_model
        )

    assert ranked == []
    assert sent == []


async def test_ranking_the_whole_chain_costs_one_query(session, engine):
    """One read for every candidate. Scoring them one at a time would be a round
    trip per level, inside the same second or two the summaries are read in."""
    _, messages = await three_candidates(session)
    for message in messages:
        await new_embedding(session, message)
    await session.commit()

    with counting_queries(engine) as sent:
        await rank_ancestors_by_similarity(
            session,
            [message.id for message in messages],
            fake_vector(QUERY_TEXT),
            settings.embedding_model,
        )

    assert len(sent) == 1
