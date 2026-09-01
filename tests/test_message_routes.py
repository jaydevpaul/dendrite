"""Route-level tests for the message + edge layer (backend B1).

Three groups carry the weight here:

* **ownership and scoping** — a message may only attach to a parent inside the
  same conversation, and that conversation must belong to the caller. Without
  it, `parent_message_id` is a way to hang your branch off a stranger's message
  and read their text into your composed context once Layer C exists.
* **the anchor** — the five CHECK constraints in section 9 have never been
  exercised by anything. Half of them are unreachable through the API because
  Pydantic rejects the request first; the tests assert the *status code* the
  caller sees, so it does not matter which layer refuses, only that it is a 422
  and not a 500.
* **rollback** — every rejection is checked by re-reading the conversation, not
  just by its status code. A 409 that still leaves a message behind would pass
  a status-only assertion.
"""

from uuid import uuid4

ALICE = ("alice@example.com", "a-good-password")
BOB = ("bob@example.com", "another-password")

# The assistant text a branch anchors into, and the exact offsets of the phrase
# "trade recall for speed" inside it. Computed rather than written by hand, so
# the fixture cannot drift out of agreement with itself.
PARENT_TEXT = "pgvector uses HNSW indexes, which trade recall for speed."
ANCHOR_TEXT = "trade recall for speed"
ANCHOR_START = PARENT_TEXT.index(ANCHOR_TEXT)
ANCHOR_END = ANCHOR_START + len(ANCHOR_TEXT)


async def signup(client, who):
    email, password = who
    return await client.post(
        "/auth/signup", json={"email": email, "password": password}
    )


async def login_as(client, who):
    """Switch the client's identity. Set-Cookie replaces the session cookie."""
    email, password = who
    return await client.post(
        "/auth/login", json={"email": email, "password": password}
    )


async def new_conversation(client, **body):
    response = await client.post("/conversations", json=body)
    return response.json()["id"]


async def post_message(client, conversation_id, **body):
    return await client.post(
        f"/conversations/{conversation_id}/messages", json=body
    )


async def get_graph(client, conversation_id):
    return await client.get(f"/conversations/{conversation_id}/messages")


async def seeded(client, who=ALICE):
    """A signed-up user with a conversation, a root question and one reply.

    Returns (conversation_id, root_message, assistant_message) -- the shape
    almost every test below starts from, since anchoring needs a parent whose
    text is known.
    """
    await signup(client, who)
    conversation_id = await new_conversation(client)

    root = (
        await post_message(client, conversation_id, role="user", content="explain HNSW")
    ).json()["message"]

    reply = (
        await post_message(
            client,
            conversation_id,
            role="assistant",
            content=PARENT_TEXT,
            parent_message_id=root["id"],
        )
    ).json()["message"]

    return conversation_id, root, reply


# --- the root message -------------------------------------------------


async def test_first_message_becomes_the_root_and_has_no_edge(client):
    await signup(client, ALICE)
    conversation_id = await new_conversation(client)

    response = await post_message(client, conversation_id, role="user", content="hello")
    assert response.status_code == 201

    body = response.json()
    assert body["message"]["role"] == "user"
    assert body["message"]["content"] == "hello"
    assert body["message"]["conversation_id"] == conversation_id
    # Nothing came before it, so there is no link to record.
    assert body["edge"] is None

    conversation = (await client.get(f"/conversations/{conversation_id}")).json()
    assert conversation["root_message_id"] == body["message"]["id"]


async def test_a_second_parentless_message_is_a_409(client):
    await signup(client, ALICE)
    conversation_id = await new_conversation(client)
    await post_message(client, conversation_id, role="user", content="first")

    response = await post_message(client, conversation_id, role="user", content="second")
    assert response.status_code == 409


async def test_the_rejected_second_root_leaves_nothing_behind(client):
    """The whole request rolls back, message included.

    create_message flushes the message *before* trying to claim the root, so a
    409 has an INSERT already sent to the database. If the service raised
    without rolling back, the message would be committed as an unreachable
    orphan and only this assertion would notice.
    """
    await signup(client, ALICE)
    conversation_id = await new_conversation(client)
    await post_message(client, conversation_id, role="user", content="first")

    await post_message(client, conversation_id, role="user", content="second")

    graph = (await get_graph(client, conversation_id)).json()
    assert [message["content"] for message in graph["messages"]] == ["first"]


async def test_root_message_id_is_not_reassigned_by_later_messages(client):
    conversation_id, root, _reply = await seeded(client)

    conversation = (await client.get(f"/conversations/{conversation_id}")).json()
    assert conversation["root_message_id"] == root["id"]


# --- continuations vs branches ----------------------------------------


async def test_a_message_with_a_parent_and_no_anchor_is_a_continuation(client):
    conversation_id, _root, reply = await seeded(client)

    response = await post_message(
        client,
        conversation_id,
        role="user",
        content="And what does that cost per call?",
        parent_message_id=reply["id"],
    )
    assert response.status_code == 201

    edge = response.json()["edge"]
    assert edge["parent_message_id"] == reply["id"]
    assert edge["child_message_id"] == response.json()["message"]["id"]
    # Section 6: all three anchor fields null is what *makes* it a continuation.
    assert edge["anchor_start"] is None
    assert edge["anchor_end"] is None
    assert edge["anchored_text"] is None
    assert edge["strategy_override"] is None


async def test_a_message_with_an_anchor_is_a_branch(client):
    conversation_id, _root, reply = await seeded(client)

    response = await post_message(
        client,
        conversation_id,
        role="user",
        content="Does that recall loss matter for us?",
        parent_message_id=reply["id"],
        anchor_start=ANCHOR_START,
        anchor_end=ANCHOR_END,
        anchored_text=ANCHOR_TEXT,
    )
    assert response.status_code == 201

    edge = response.json()["edge"]
    assert edge["anchor_start"] == ANCHOR_START
    assert edge["anchor_end"] == ANCHOR_END
    assert edge["anchored_text"] == ANCHOR_TEXT


async def test_one_parent_can_carry_both_a_continuation_and_a_branch(client):
    conversation_id, _root, reply = await seeded(client)

    straight_on = await post_message(
        client,
        conversation_id,
        role="user",
        content="And the cost?",
        parent_message_id=reply["id"],
    )
    branched = await post_message(
        client,
        conversation_id,
        role="user",
        content="Does recall loss matter?",
        parent_message_id=reply["id"],
        anchor_start=ANCHOR_START,
        anchor_end=ANCHOR_END,
        anchored_text=ANCHOR_TEXT,
    )

    assert straight_on.status_code == 201
    assert branched.status_code == 201
    # child_message_id is UNIQUE, parent_message_id is not: a message has at
    # most one parent and any number of children.
    assert (
        straight_on.json()["edge"]["parent_message_id"]
        == branched.json()["edge"]["parent_message_id"]
    )


async def test_two_assistant_messages_can_share_one_user_parent(client):
    """The shape regeneration produces. Nothing enforces role alternation.

    Section 9 makes a node one message, not one turn, and section 6 locks
    "regeneration never deletes" -- so a user message with two assistant
    children is a legal graph, and an alternation rule added here would have to
    be removed the moment generation lands.
    """
    await signup(client, ALICE)
    conversation_id = await new_conversation(client)
    root = (
        await post_message(client, conversation_id, role="user", content="explain HNSW")
    ).json()["message"]

    first = await post_message(
        client,
        conversation_id,
        role="assistant",
        content="Answer, take one.",
        parent_message_id=root["id"],
    )
    second = await post_message(
        client,
        conversation_id,
        role="assistant",
        content="Answer, take two.",
        parent_message_id=root["id"],
    )

    assert first.status_code == 201
    assert second.status_code == 201


async def test_a_user_message_can_follow_a_user_message(client):
    await signup(client, ALICE)
    conversation_id = await new_conversation(client)
    root = (
        await post_message(client, conversation_id, role="user", content="one thing")
    ).json()["message"]

    response = await post_message(
        client,
        conversation_id,
        role="user",
        content="and another thing",
        parent_message_id=root["id"],
    )
    assert response.status_code == 201


# --- anchor validation ------------------------------------------------


async def test_anchored_text_must_match_the_parent_at_that_offset(client):
    """No CHECK constraint can catch this -- it needs the parent's row.

    A CHECK constraint only sees the row being written, so the database will
    happily store an anchor whose text disagrees with the text it points at.
    The service compares them; this is the test that says so.
    """
    conversation_id, _root, reply = await seeded(client)

    response = await post_message(
        client,
        conversation_id,
        role="user",
        content="branch",
        parent_message_id=reply["id"],
        anchor_start=ANCHOR_START,
        anchor_end=ANCHOR_END,
        anchored_text="something else entirely",
    )
    assert response.status_code == 422


async def test_anchor_cannot_run_past_the_end_of_the_parent(client):
    conversation_id, _root, reply = await seeded(client)

    response = await post_message(
        client,
        conversation_id,
        role="user",
        content="branch",
        parent_message_id=reply["id"],
        anchor_start=0,
        anchor_end=len(PARENT_TEXT) + 50,
        anchored_text=PARENT_TEXT,
    )
    assert response.status_code == 422


async def test_a_rejected_anchor_leaves_no_message_behind(client):
    conversation_id, _root, reply = await seeded(client)

    await post_message(
        client,
        conversation_id,
        role="user",
        content="should not exist",
        parent_message_id=reply["id"],
        anchor_start=ANCHOR_START,
        anchor_end=ANCHOR_END,
        anchored_text="wrong",
    )

    graph = (await get_graph(client, conversation_id)).json()
    assert "should not exist" not in [m["content"] for m in graph["messages"]]
    assert len(graph["messages"]) == 2


async def test_a_partial_anchor_is_rejected(client):
    """Mirrors ck_edge_anchor_all_or_nothing: 0 or 3 of the fields, never 1.

    Rejected by the schema before any SQL runs, so the caller gets a 422 naming
    the problem instead of a 500 from an IntegrityError.
    """
    conversation_id, _root, reply = await seeded(client)

    response = await post_message(
        client,
        conversation_id,
        role="user",
        content="branch",
        parent_message_id=reply["id"],
        anchor_start=ANCHOR_START,
    )
    assert response.status_code == 422


async def test_an_anchor_with_no_parent_is_rejected(client):
    await signup(client, ALICE)
    conversation_id = await new_conversation(client)

    response = await post_message(
        client,
        conversation_id,
        role="user",
        content="branch",
        anchor_start=0,
        anchor_end=4,
        anchored_text="what",
    )
    assert response.status_code == 422


async def test_anchor_end_must_be_after_anchor_start(client):
    conversation_id, _root, reply = await seeded(client)

    response = await post_message(
        client,
        conversation_id,
        role="user",
        content="branch",
        parent_message_id=reply["id"],
        anchor_start=10,
        anchor_end=10,
        anchored_text="x",
    )
    assert response.status_code == 422


async def test_anchor_start_cannot_be_negative(client):
    conversation_id, _root, reply = await seeded(client)

    response = await post_message(
        client,
        conversation_id,
        role="user",
        content="branch",
        parent_message_id=reply["id"],
        anchor_start=-1,
        anchor_end=5,
        anchored_text="pgvec",
    )
    assert response.status_code == 422


async def test_anchored_text_cannot_be_empty(client):
    conversation_id, _root, reply = await seeded(client)

    response = await post_message(
        client,
        conversation_id,
        role="user",
        content="branch",
        parent_message_id=reply["id"],
        anchor_start=0,
        anchor_end=8,
        anchored_text="",
    )
    assert response.status_code == 422


# --- strategy override ------------------------------------------------


async def test_span_only_requires_an_anchor(client):
    """Mirrors ck_edge_span_only_needs_anchor.

    SpanOnly composes context from the anchored span alone, so on an edge with
    no span it would resolve to nothing at all.
    """
    conversation_id, _root, reply = await seeded(client)

    response = await post_message(
        client,
        conversation_id,
        role="user",
        content="branch",
        parent_message_id=reply["id"],
        strategy_override="SpanOnly",
    )
    assert response.status_code == 422


async def test_span_only_is_accepted_with_an_anchor(client):
    conversation_id, _root, reply = await seeded(client)

    response = await post_message(
        client,
        conversation_id,
        role="user",
        content="branch",
        parent_message_id=reply["id"],
        anchor_start=ANCHOR_START,
        anchor_end=ANCHOR_END,
        anchored_text=ANCHOR_TEXT,
        strategy_override="SpanOnly",
    )
    assert response.status_code == 201
    assert response.json()["edge"]["strategy_override"] == "SpanOnly"


async def test_an_unknown_strategy_override_is_rejected(client):
    conversation_id, _root, reply = await seeded(client)

    response = await post_message(
        client,
        conversation_id,
        role="user",
        content="branch",
        parent_message_id=reply["id"],
        strategy_override="MakeItUp",
    )
    assert response.status_code == 422


# --- role and content -------------------------------------------------


async def test_an_unknown_role_is_rejected(client):
    await signup(client, ALICE)
    conversation_id = await new_conversation(client)

    response = await post_message(client, conversation_id, role="system", content="hi")
    assert response.status_code == 422


async def test_empty_content_is_rejected_at_the_api(client):
    """Section 9 allows an empty string in the *column* -- not in a request.

    The column has to permit "" because generation will insert a blank
    assistant message and stream into it. That write happens server-side and
    never passes through this schema, so the API can still insist that a client
    sends real text.
    """
    await signup(client, ALICE)
    conversation_id = await new_conversation(client)

    response = await post_message(client, conversation_id, role="user", content="")
    assert response.status_code == 422


async def test_whitespace_only_content_is_rejected(client):
    await signup(client, ALICE)
    conversation_id = await new_conversation(client)

    response = await post_message(client, conversation_id, role="user", content="   \n ")
    assert response.status_code == 422


async def test_content_is_stripped(client):
    await signup(client, ALICE)
    conversation_id = await new_conversation(client)

    response = await post_message(
        client, conversation_id, role="user", content="  explain HNSW  "
    )
    assert response.json()["message"]["content"] == "explain HNSW"


# --- ownership and scoping --------------------------------------------


async def test_a_parent_in_another_conversation_is_a_404(client):
    """Same user, wrong conversation. Nothing in the schema prevents this.

    edge.parent_message_id is a plain FK to message: the database checks that
    the id exists, never which conversation it sits in. The service adds
    `Message.conversation_id == conversation.id` to the lookup, which is the
    entire guard.
    """
    await signup(client, ALICE)
    first = await new_conversation(client, title="first")
    second = await new_conversation(client, title="second")

    stranger = (
        await post_message(client, first, role="user", content="over here")
    ).json()["message"]

    response = await post_message(
        client, second, role="user", content="reach across", parent_message_id=stranger["id"]
    )
    assert response.status_code == 404


async def test_a_parent_in_another_users_conversation_is_a_404(client):
    """The security case. A 403 would confirm the message id is real."""
    _alice_conversation, _root, alice_reply = await seeded(client, ALICE)

    await signup(client, BOB)
    bob_conversation = await new_conversation(client)

    response = await post_message(
        client,
        bob_conversation,
        role="user",
        content="steal alice's context",
        parent_message_id=alice_reply["id"],
    )
    assert response.status_code == 404


async def test_posting_to_another_users_conversation_is_a_404(client):
    alice_conversation, _root, _reply = await seeded(client, ALICE)

    await signup(client, BOB)
    response = await post_message(
        client, alice_conversation, role="user", content="not yours"
    )
    assert response.status_code == 404


async def test_reading_another_users_messages_is_a_404(client):
    alice_conversation, _root, _reply = await seeded(client, ALICE)

    await signup(client, BOB)
    response = await get_graph(client, alice_conversation)
    assert response.status_code == 404


async def test_an_unknown_conversation_is_a_404(client):
    await signup(client, ALICE)

    response = await post_message(client, str(uuid4()), role="user", content="hi")
    assert response.status_code == 404


async def test_messages_require_a_session(client):
    conversation_id = str(uuid4())

    assert (await get_graph(client, conversation_id)).status_code == 401
    assert (
        await post_message(client, conversation_id, role="user", content="hi")
    ).status_code == 401


# --- reading the graph ------------------------------------------------


async def test_an_empty_conversation_returns_two_empty_lists(client):
    await signup(client, ALICE)
    conversation_id = await new_conversation(client)

    response = await get_graph(client, conversation_id)
    assert response.status_code == 200
    assert response.json() == {"messages": [], "edges": []}


async def test_the_graph_returns_every_message_and_every_link(client):
    conversation_id, root, reply = await seeded(client)
    branch = (
        await post_message(
            client,
            conversation_id,
            role="user",
            content="Does recall loss matter?",
            parent_message_id=reply["id"],
            anchor_start=ANCHOR_START,
            anchor_end=ANCHOR_END,
            anchored_text=ANCHOR_TEXT,
        )
    ).json()["message"]

    graph = (await get_graph(client, conversation_id)).json()

    # Messages in creation order; uuid7 keys are time-ordered, so this is also
    # id order.
    assert [m["id"] for m in graph["messages"]] == [root["id"], reply["id"], branch["id"]]

    # Two messages have a parent, so there are two edges -- the root has none.
    links = {(e["parent_message_id"], e["child_message_id"]) for e in graph["edges"]}
    assert links == {(root["id"], reply["id"]), (reply["id"], branch["id"])}


async def test_the_graph_only_contains_this_conversation(client):
    await signup(client, ALICE)
    first = await new_conversation(client, title="first")
    second = await new_conversation(client, title="second")

    await post_message(client, first, role="user", content="in the first")
    await post_message(client, second, role="user", content="in the second")

    graph = (await get_graph(client, first)).json()
    assert [m["content"] for m in graph["messages"]] == ["in the first"]


# --- conversation activity --------------------------------------------


async def test_a_new_message_moves_the_conversations_updated_at(client):
    """So the sidebar's "most recent first" means most recent *activity*.

    Nothing else would move it: a message write touches the message and edge
    tables, not the conversation row, so without an explicit bump a busy
    conversation would keep sorting by the moment it was created.
    """
    conversation_id, _root, reply = await seeded(client)
    before = (await client.get(f"/conversations/{conversation_id}")).json()["updated_at"]

    await post_message(
        client,
        conversation_id,
        role="user",
        content="one more",
        parent_message_id=reply["id"],
    )

    after = (await client.get(f"/conversations/{conversation_id}")).json()["updated_at"]
    assert after > before
