"""Service-level tests for strategy resolution (backend B2.3, sections 6 + 8.13).

The rule being tested, in one line: **the walk never crosses a branch
boundary.** Any anchored edge ends it - with its override if it has a usable
one, with the conversation default if it does not. Continuations keep the walk
going.

Every test asserts `source` as well as `strategy`. That is the point of the
field: several rules produce `Conversation.default_strategy` as their answer -
the root, a branch boundary, a walk that reached the root, the safety cap - so
a test that checked only the strategy would pass for a resolution arriving at
the right answer down entirely the wrong path.

The fork tests are here for the same reason they are in the walk tests: a
recursive step joined on `parent_message_id` walks *down* the tree, and a
sibling's override is what then leaks in.
"""

import pytest

from app.services.ancestors import MessageNotFound, resolve_strategy
from tests.graph_builders import (
    PARENT_TEXT,
    SPAN,
    chain_of,
    link,
    new_conversation,
    new_message,
    new_user,
)


async def trunk(session, default_strategy="HierarchicalDecay"):
    """A root question and the assistant reply a branch can anchor into.

        root  (user)
        |
        reply (assistant: PARENT_TEXT)

    Returns (conversation, root, reply).
    """
    user = await new_user(session)
    conversation = await new_conversation(session, user, default_strategy)

    root = await new_message(session, conversation, "user", "explain HNSW")
    reply = await new_message(session, conversation, "assistant", PARENT_TEXT)
    await link(session, root, reply)

    return conversation, root, reply


# --- the two ends: the root, and no override anywhere ------------------


async def test_the_root_falls_back_to_the_conversation_default(session):
    """A root message has no parent edge, so there is nothing to walk."""
    conversation, root, _reply = await trunk(session, "ParentOnly")
    await session.commit()

    resolved = await resolve_strategy(session, conversation, root.id)

    assert resolved.strategy == "ParentOnly"
    assert resolved.source == "conversation_default"
    assert resolved.edge_id is None


async def test_a_continuation_chain_with_no_overrides_reaches_the_root(session):
    conversation, _root, _reply = await trunk(session, "FullInheritance")
    chain = await chain_of(session, conversation, 5)
    await session.commit()

    resolved = await resolve_strategy(session, conversation, chain[-1].id)

    assert resolved.strategy == "FullInheritance"
    assert resolved.source == "conversation_default"
    assert resolved.edge_id is None


async def test_the_fallback_is_read_live_not_captured(session):
    """Changing the conversation default changes later resolutions.

    Section 8.13 leans on this: PATCH /conversations/{id} with a new
    default_strategy is the user-facing "compose everything from here on this
    way" control, and it only works if resolution reads the column at compose
    time rather than at creation.
    """
    conversation, _root, _reply = await trunk(session, "ParentOnly")
    chain = await chain_of(session, conversation, 4)
    await session.commit()

    before = await resolve_strategy(session, conversation, chain[-1].id)
    assert before.strategy == "ParentOnly"

    conversation.default_strategy = "HierarchicalDecay"
    await session.commit()

    after = await resolve_strategy(session, conversation, chain[-1].id)
    assert after.strategy == "HierarchicalDecay"
    assert after.source == "conversation_default"


# --- the branch default (section 5, applied at resolution time) --------


async def test_a_branch_with_no_override_resolves_to_span_only(session):
    """Section 5: "branches default to SpanOnly at creation."

    Nothing is written into the edge - section 8.13 applies the default here,
    at read time, which is what keeps section 6's "null on branches that accept
    the default" true.
    """
    conversation, _root, reply = await trunk(session)
    branch = await new_message(session, conversation, "user", "why is recall lower?")
    edge = await link(session, reply, branch, anchor=SPAN)
    await session.commit()

    resolved = await resolve_strategy(session, conversation, branch.id)

    assert resolved.strategy == "SpanOnly"
    assert resolved.source == "branch_default"
    assert resolved.edge_id == edge.id


async def test_a_continuation_under_a_blank_branch_gets_the_default(session):
    """Not SpanOnly. Section 5 locks it "valid on branches only".

    A continuation inside the branch composing only the branch's anchored span
    would drop everything typed inside the branch since - not a strategy
    anyone chose. So the branch has nothing usable to offer, and the walk stops
    there rather than climbing past it.
    """
    conversation, _root, reply = await trunk(session, "HierarchicalDecay")
    branch = await new_message(session, conversation, "user", "why is recall lower?")
    branch_edge = await link(session, reply, branch, anchor=SPAN)

    inside = await new_message(session, conversation, "user", "and the cost?")
    await link(session, branch, inside)
    await session.commit()

    resolved = await resolve_strategy(session, conversation, inside.id)

    assert resolved.strategy == "HierarchicalDecay"
    assert resolved.source == "branch_boundary"
    assert resolved.edge_id == branch_edge.id


# --- an override that is found -----------------------------------------


async def test_an_override_on_the_immediate_edge_wins(session):
    conversation, _root, reply = await trunk(session, "ParentOnly")
    branch = await new_message(session, conversation, "user", "with an override")
    edge = await link(session, reply, branch, anchor=SPAN, override="FullInheritance")
    await session.commit()

    resolved = await resolve_strategy(session, conversation, branch.id)

    assert resolved.strategy == "FullInheritance"
    assert resolved.source == "edge"
    assert resolved.edge_id == edge.id


async def test_a_continuation_inherits_the_branchs_override(session):
    """Section 6's "nested branches govern their own subtree" still holds.

    An explicit override *on* the branch edge reaches everything below it. Only
    a *blank* branch stops the walk.
    """
    conversation, _root, reply = await trunk(session, "ParentOnly")
    branch = await new_message(session, conversation, "user", "with an override")
    edge = await link(session, reply, branch, anchor=SPAN, override="FullInheritance")

    inside = await new_message(session, conversation, "user", "inside the branch")
    await link(session, branch, inside)
    deeper = await new_message(session, conversation, "user", "deeper still")
    await link(session, inside, deeper)
    await session.commit()

    resolved = await resolve_strategy(session, conversation, deeper.id)

    assert resolved.strategy == "FullInheritance"
    assert resolved.source == "edge"
    assert resolved.edge_id == edge.id


async def test_the_nearest_override_wins(session):
    """Two overrides in the ancestry; the closer one governs."""
    conversation, _root, reply = await trunk(session)
    outer = await new_message(session, conversation, "user", "outer branch")
    await link(session, reply, outer, anchor=SPAN, override="FullInheritance")

    inner = await new_message(session, conversation, "user", "inner")
    near = await link(session, outer, inner, override="ParentOnly")
    below = await new_message(session, conversation, "user", "below the inner one")
    await link(session, inner, below)
    await session.commit()

    resolved = await resolve_strategy(session, conversation, below.id)

    assert resolved.strategy == "ParentOnly"
    assert resolved.source == "edge"
    assert resolved.edge_id == near.id


async def test_an_override_on_a_continuation_is_honoured(session):
    """Section 6 says the column is null on continuations; nothing enforces it.

    Section 8.13 leaves it permitted deliberately - section 7's eval harness
    wants to pin a strategy at an arbitrary point in a fixture graph without
    going through the branch machinery. So a non-null override on a
    continuation edge must actually resolve, not be ignored.
    """
    conversation, _root, _reply = await trunk(session, "ParentOnly")
    chain = await chain_of(session, conversation, 4)
    mid = await link(
        session,
        chain[-1],
        await new_message(session, conversation, "user", "mid-trunk change"),
        override="HierarchicalDecay",
    )
    await session.commit()

    resolved = await resolve_strategy(session, conversation, mid.child_message_id)

    assert resolved.strategy == "HierarchicalDecay"
    assert resolved.source == "edge"
    assert resolved.edge_id == mid.id


# --- SpanOnly is never inherited ---------------------------------------


async def test_an_explicit_span_only_branch_resolves_to_span_only(session):
    conversation, _root, reply = await trunk(session)
    branch = await new_message(session, conversation, "user", "span branch")
    edge = await link(session, reply, branch, anchor=SPAN, override="SpanOnly")
    await session.commit()

    resolved = await resolve_strategy(session, conversation, branch.id)

    assert resolved.strategy == "SpanOnly"
    assert resolved.source == "edge"
    assert resolved.edge_id == edge.id


async def test_span_only_is_not_inherited_by_a_continuation(session):
    """The one exclusion in "usable" (section 8.13).

    Seen from below, an explicit SpanOnly is not an answer - a continuation has
    no span of its own. It is a branch boundary like any other, so the answer
    is the conversation default.
    """
    conversation, _root, reply = await trunk(session, "HierarchicalDecayWithRetrieval")
    branch = await new_message(session, conversation, "user", "span branch")
    edge = await link(session, reply, branch, anchor=SPAN, override="SpanOnly")

    below = await new_message(session, conversation, "user", "below it")
    await link(session, branch, below)
    await session.commit()

    resolved = await resolve_strategy(session, conversation, below.id)

    assert resolved.strategy == "HierarchicalDecayWithRetrieval"
    assert resolved.source == "branch_boundary"
    assert resolved.edge_id == edge.id


# --- forks: a sibling's override must not leak -------------------------


async def test_a_siblings_override_is_not_inherited(session):
    """Two branches off one reply. Only one carries an override.

    A recursive step joined the wrong way round walks down into the sibling,
    and this is where that shows up as a wrong *strategy* rather than a wrong
    ancestor list.
    """
    conversation, _root, reply = await trunk(session, "ParentOnly")

    with_override = await new_message(session, conversation, "user", "has one")
    await link(session, reply, with_override, anchor=SPAN, override="FullInheritance")

    without = await new_message(session, conversation, "user", "has none")
    plain_edge = await link(session, reply, without, anchor=(15, 28))
    await session.commit()

    resolved = await resolve_strategy(session, conversation, without.id)

    assert resolved.strategy == "SpanOnly"
    assert resolved.source == "branch_default"
    assert resolved.edge_id == plain_edge.id


async def test_the_sibling_that_has_an_override_still_gets_it(session):
    """Asserted from both sides of the fork, not just one."""
    conversation, _root, reply = await trunk(session, "ParentOnly")

    with_override = await new_message(session, conversation, "user", "has one")
    edge = await link(
        session, reply, with_override, anchor=SPAN, override="FullInheritance"
    )

    without = await new_message(session, conversation, "user", "has none")
    await link(session, reply, without, anchor=(15, 28))
    await session.commit()

    resolved = await resolve_strategy(session, conversation, with_override.id)

    assert resolved.strategy == "FullInheritance"
    assert resolved.source == "edge"
    assert resolved.edge_id == edge.id


async def test_a_regenerated_siblings_override_is_not_inherited(session):
    """The commonest fork: one user message, two assistant children."""
    conversation, _root, _reply = await trunk(session, "ParentOnly")

    prompt = await new_message(session, conversation, "user", "explain HNSW")
    kept = await new_message(session, conversation, "assistant", "kept")
    discarded = await new_message(session, conversation, "assistant", "regenerated")
    await link(session, prompt, kept)
    await link(session, prompt, discarded, override="FullInheritance")

    follow_up = await new_message(session, conversation, "user", "go on")
    await link(session, kept, follow_up)
    await session.commit()

    resolved = await resolve_strategy(session, conversation, follow_up.id)

    assert resolved.strategy == "ParentOnly"
    assert resolved.source == "conversation_default"


# --- the safety cap ----------------------------------------------------


async def test_the_depth_cap_reports_itself(session):
    """Section 8.6 requires degradations be visible rather than silent.

    The answer at the cap is the same as the answer at the root in every
    realistic case, so the strategy alone cannot tell you the cap fired -
    which is what `source` is for.
    """
    conversation, _root, _reply = await trunk(session, "HierarchicalDecay")
    chain = await chain_of(session, conversation, 6)
    await session.commit()

    resolved = await resolve_strategy(
        session, conversation, chain[-1].id, max_depth=2
    )

    assert resolved.strategy == "HierarchicalDecay"
    assert resolved.source == "depth_cap"


async def test_a_cap_larger_than_the_chain_does_not_report_itself(session):
    """The off-by-one guard on the test above."""
    conversation, _root, _reply = await trunk(session, "HierarchicalDecay")
    chain = await chain_of(session, conversation, 3)
    await session.commit()

    resolved = await resolve_strategy(
        session, conversation, chain[-1].id, max_depth=50
    )

    assert resolved.source == "conversation_default"


async def test_a_max_depth_below_one_is_refused(session):
    """Zero levels cannot answer anything, so it is a programming error."""
    conversation, _root, reply = await trunk(session)
    await session.commit()

    with pytest.raises(ValueError):
        await resolve_strategy(session, conversation, reply.id, max_depth=0)


# --- scoping -----------------------------------------------------------


async def test_an_override_in_another_conversation_is_unreachable(session):
    """The security case, and unbuildable through the API (section 8.12).

    Without the conversation filter inside the CTE, a stranger's edge would not
    only leak its strategy - the walk would climb through it into their
    messages, which is what the composition layer then reads as text.
    """
    conversation, _root, reply = await trunk(session, "HierarchicalDecay")
    branch = await new_message(session, conversation, "user", "theirs")
    await link(session, reply, branch, anchor=SPAN, override="FullInheritance")

    user = await new_user(session, email="second@example.com")
    other = await new_conversation(session, user, "ParentOnly")
    intruder = await new_message(session, other, "user", "mine")
    await link(session, branch, intruder)  # parent lives in the other conversation
    await session.commit()

    resolved = await resolve_strategy(session, other, intruder.id)

    assert resolved.strategy == "ParentOnly"
    assert resolved.source == "conversation_default"


async def test_a_message_in_another_conversation_is_not_found(session):
    conversation, _root, reply = await trunk(session)
    other = await new_conversation(session, await new_user(session, "x@example.com"))
    await session.commit()

    with pytest.raises(MessageNotFound):
        await resolve_strategy(session, other, reply.id)
