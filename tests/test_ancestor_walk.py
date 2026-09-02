"""Service-level tests for the ancestor walk (backend B2.2, spec section 8.4).

These go through the service rather than HTTP, for two reasons. The walk has no
route yet - that is B2.4 - and more importantly some of what has to be tested
cannot be built through the API at all: a cross-conversation edge is refused by
`create_message` (section 8.12), so the only way to prove the walk refuses it
too is to insert one directly here.

Where the weight sits:

* **forks.** The single likeliest bug is joining the recursive step on
  `parent_message_id` instead of `child_message_id` - which walks *down* the
  tree instead of up. That version behaves perfectly on a straight-line chain,
  so a suite without forks in it would pass a completely wrong query. Every
  fixture below that has a fork exists for this reason.
* **the depth boundary.** "Exactly at the cap" and "one past the cap" are
  different code paths, because truncation is detected by recursing one level
  further than asked and discarding that row.
* **the conversation boundary.** The walk is what eventually pulls ancestor
  *text* into a composed context, so a walk that steps into another
  conversation is a data leak, not a wrong answer.
"""

from uuid import uuid4

import pytest

from app.models.conversation import Conversation
from app.models.edge import Edge
from app.models.message import Message
from app.models.user import User
from app.services.ancestors import MessageNotFound, walk_ancestors

PARENT_TEXT = "pgvector uses HNSW indexes, which trade recall for speed."
ANCHOR_TEXT = "trade recall for speed"
ANCHOR_START = PARENT_TEXT.index(ANCHOR_TEXT)
ANCHOR_END = ANCHOR_START + len(ANCHOR_TEXT)


# --- fixture builders --------------------------------------------------
#
# Deliberately not going through the API. The API is B1's business and is
# already tested; here the point is to build graph shapes directly, including
# ones the API would refuse.


async def new_user(session, email="walker@example.com"):
    user = User(email=email, password_hash="not-a-real-hash")
    session.add(user)
    await session.flush()
    return user


async def new_conversation(session, user, default_strategy="HierarchicalDecay"):
    conversation = Conversation(user_id=user.id, default_strategy=default_strategy)
    session.add(conversation)
    await session.flush()
    return conversation


async def new_message(session, conversation, role="user", content="a message"):
    message = Message(
        conversation_id=conversation.id, role=role, content=content
    )
    session.add(message)
    await session.flush()
    return message


async def link(session, parent, child, anchor=None):
    """Attach child under parent. `anchor` makes it a branch, None a continuation."""
    edge = Edge(parent_message_id=parent.id, child_message_id=child.id)

    if anchor is not None:
        start, end = anchor
        edge.anchor_start = start
        edge.anchor_end = end
        edge.anchored_text = parent.content[start:end]

    session.add(edge)
    await session.flush()
    return edge


async def forked_graph(session):
    """The shape almost every test below needs.

        A  (user: explain HNSW)
        |
        B  (assistant: PARENT_TEXT)
        |\\
        | \\
        C  E     C is a branch anchored on "trade recall for speed",
        |        E is a branch anchored on a different span
        D        D is a plain continuation under C

    Returns the conversation and the five messages, plus the four edges.
    """
    user = await new_user(session)
    conversation = await new_conversation(session, user)

    a = await new_message(session, conversation, "user", "explain HNSW")
    b = await new_message(session, conversation, "assistant", PARENT_TEXT)
    c = await new_message(session, conversation, "user", "why is recall lower?")
    d = await new_message(session, conversation, "user", "and the cost per call?")
    e = await new_message(session, conversation, "user", "what is an HNSW index?")

    ab = await link(session, a, b)
    bc = await link(session, b, c, anchor=(ANCHOR_START, ANCHOR_END))
    cd = await link(session, c, d)
    be = await link(session, b, e, anchor=(15, 28))

    await session.commit()

    return {
        "conversation": conversation,
        "user": user,
        "a": a, "b": b, "c": c, "d": d, "e": e,
        "ab": ab, "bc": bc, "cd": cd, "be": be,
    }


# --- the chain ---------------------------------------------------------


async def test_the_walk_returns_the_chain_nearest_first(session):
    g = await forked_graph(session)

    walk = await walk_ancestors(session, g["conversation"], g["d"].id)

    assert [step.message.id for step in walk.steps] == [
        g["c"].id, g["b"].id, g["a"].id
    ]
    assert [step.depth for step in walk.steps] == [1, 2, 3]
    assert walk.truncated is False


async def test_the_starting_message_is_not_in_its_own_walk(session):
    """Ancestors only (section 8.13). A depth-0 row would be an off-by-one trap."""
    g = await forked_graph(session)

    walk = await walk_ancestors(session, g["conversation"], g["d"].id)

    assert g["d"].id not in [step.message.id for step in walk.steps]


async def test_each_step_carries_the_edge_that_links_it_downward(session):
    """Not the edge above the ancestor - the one below it.

    Step 1 is the parent, and its edge is the one attaching the *starting*
    message. That is the edge holding the anchor, which is the entire input to
    SpanOnly and to the "span full" half of HierarchicalDecay. Off by one here
    and the composer anchors into the wrong message.
    """
    g = await forked_graph(session)

    walk = await walk_ancestors(session, g["conversation"], g["d"].id)

    assert [step.edge.id for step in walk.steps] == [
        g["cd"].id, g["bc"].id, g["ab"].id
    ]

    # D was attached by a plain continuation, so step 1 has no anchor...
    assert walk.steps[0].edge.anchored_text is None
    # ...while C was attached by a branch, so step 2 carries the span.
    assert walk.steps[1].edge.anchored_text == ANCHOR_TEXT
    assert walk.steps[1].edge.anchor_start == ANCHOR_START


async def test_the_walk_reaches_the_root_by_default(session):
    """No default cap of 3 (section 8.13 clarifies 8.4's "~3" is a fidelity tier).

    A chain of twelve, walked with no max_depth: all eleven ancestors come back.
    If the default were 3 this test is what fails, and FullInheritance - "the
    entire ancestor chain" - would be unbuildable.
    """
    user = await new_user(session)
    conversation = await new_conversation(session, user)

    chain = [await new_message(session, conversation, "user", "m0")]
    for i in range(1, 12):
        role = "assistant" if i % 2 else "user"
        child = await new_message(session, conversation, role, f"m{i}")
        await link(session, chain[-1], child)
        chain.append(child)
    await session.commit()

    walk = await walk_ancestors(session, conversation, chain[-1].id)

    assert len(walk.steps) == 11
    assert walk.truncated is False
    assert [step.message.content for step in walk.steps] == [
        f"m{i}" for i in range(10, -1, -1)
    ]


# --- forks: the walk must go up, never down or sideways ----------------


async def test_a_sibling_branch_is_not_an_ancestor(session):
    """E hangs off the same parent as C. Walking from D must never see it.

    This is the test that a downward join fails.
    """
    g = await forked_graph(session)

    walk = await walk_ancestors(session, g["conversation"], g["d"].id)

    assert g["e"].id not in [step.message.id for step in walk.steps]


async def test_the_other_side_of_the_fork_walks_its_own_chain(session):
    """Asserted from E as well as from D - a bug may return only one sibling."""
    g = await forked_graph(session)

    walk = await walk_ancestors(session, g["conversation"], g["e"].id)

    assert [step.message.id for step in walk.steps] == [g["b"].id, g["a"].id]
    assert not {g["c"].id, g["d"].id} & {step.message.id for step in walk.steps}


async def test_a_regenerated_sibling_is_not_an_ancestor(session):
    """Section 6 locks "regeneration never deletes", so one user message with
    two assistant children is a legal graph - and the commonest fork there is.
    """
    user = await new_user(session)
    conversation = await new_conversation(session, user)

    prompt = await new_message(session, conversation, "user", "explain HNSW")
    first = await new_message(session, conversation, "assistant", "first attempt")
    second = await new_message(session, conversation, "assistant", "regenerated")
    await link(session, prompt, first)
    await link(session, prompt, second)

    follow_up = await new_message(session, conversation, "user", "go on")
    await link(session, second, follow_up)
    await session.commit()

    walk = await walk_ancestors(session, conversation, follow_up.id)

    assert [step.message.id for step in walk.steps] == [second.id, prompt.id]
    assert first.id not in [step.message.id for step in walk.steps]


async def test_a_fan_out_above_the_walk_returns_one_node_per_level(session):
    """Every level of the chain also has an unrelated sibling hanging off it.

    A downward or sideways join shows up here as more steps than levels.
    """
    user = await new_user(session)
    conversation = await new_conversation(session, user)

    root = await new_message(session, conversation, "user", "level 0")
    spine = [root]
    for i in range(1, 4):
        child = await new_message(session, conversation, "user", f"level {i}")
        await link(session, spine[-1], child)
        spine.append(child)

        distraction = await new_message(session, conversation, "user", f"aside {i}")
        await link(session, spine[-2], distraction)
    await session.commit()

    walk = await walk_ancestors(session, conversation, spine[-1].id)

    assert [step.message.content for step in walk.steps] == [
        "level 2", "level 1", "level 0"
    ]


# --- the depth boundary ------------------------------------------------


async def test_max_depth_truncates_and_says_so(session):
    g = await forked_graph(session)

    walk = await walk_ancestors(session, g["conversation"], g["d"].id, max_depth=2)

    assert [step.message.id for step in walk.steps] == [g["c"].id, g["b"].id]
    assert walk.truncated is True


async def test_a_chain_exactly_at_max_depth_is_not_truncated(session):
    """The off-by-one. D has exactly three ancestors, asked for three.

    Truncation is detected by recursing one level *past* the limit and throwing
    that row away, so "exactly at the cap" and "one past it" are different
    paths. An implementation that sets truncated = (len(steps) == max_depth)
    passes the test above and fails this one.
    """
    g = await forked_graph(session)

    walk = await walk_ancestors(session, g["conversation"], g["d"].id, max_depth=3)

    assert len(walk.steps) == 3
    assert walk.truncated is False


async def test_max_depth_one_returns_only_the_parent(session):
    """What ParentOnly asks for."""
    g = await forked_graph(session)

    walk = await walk_ancestors(session, g["conversation"], g["d"].id, max_depth=1)

    assert [step.message.id for step in walk.steps] == [g["c"].id]
    assert walk.truncated is True


async def test_max_depth_zero_returns_nothing(session):
    """What SpanOnly would ask for, if it asked at all."""
    g = await forked_graph(session)

    walk = await walk_ancestors(session, g["conversation"], g["d"].id, max_depth=0)

    assert walk.steps == []
    assert walk.truncated is True


async def test_a_negative_max_depth_is_refused(session):
    """Not defensive noise: the result is sliced with [:max_depth], and a
    negative slice silently drops the *last* ancestor instead of erroring.
    """
    g = await forked_graph(session)

    with pytest.raises(ValueError):
        await walk_ancestors(session, g["conversation"], g["d"].id, max_depth=-1)


# --- the root ----------------------------------------------------------


async def test_the_root_has_no_ancestors(session):
    g = await forked_graph(session)

    walk = await walk_ancestors(session, g["conversation"], g["a"].id)

    assert walk.steps == []
    assert walk.truncated is False


# --- scoping -----------------------------------------------------------


async def test_the_walk_stops_at_a_conversation_boundary(session):
    """The security case, and it cannot be built through the API.

    create_message refuses a parent in another conversation (section 8.12), so
    this edge is inserted directly. If that guard ever regressed - or a future
    import path wrote one - the walk is where a stranger's message text would
    enter a composed context. The filter lives inside the CTE so the walk is
    safe on its own terms, not by trusting a check made elsewhere.
    """
    g = await forked_graph(session)
    other = await new_conversation(session, g["user"])

    intruder = await new_message(session, other, "user", "different conversation")
    await link(session, g["b"], intruder)  # parent is in the *first* conversation
    await session.commit()

    walk = await walk_ancestors(session, other, intruder.id)

    assert walk.steps == []
    assert walk.truncated is False


async def test_a_message_in_another_conversation_is_not_found(session):
    """Same user, wrong conversation. 404 territory, not an empty walk -
    an empty walk would be indistinguishable from "this is the root".
    """
    g = await forked_graph(session)
    other = await new_conversation(session, g["user"])
    await session.commit()

    with pytest.raises(MessageNotFound):
        await walk_ancestors(session, other, g["d"].id)


async def test_a_message_in_another_users_conversation_is_not_found(session):
    g = await forked_graph(session)
    bob = await new_user(session, email="bob@example.com")
    bob_conversation = await new_conversation(session, bob)
    await session.commit()

    with pytest.raises(MessageNotFound):
        await walk_ancestors(session, bob_conversation, g["d"].id)


async def test_an_unknown_message_id_is_not_found(session):
    g = await forked_graph(session)

    with pytest.raises(MessageNotFound):
        await walk_ancestors(session, g["conversation"], uuid4())
