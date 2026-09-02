"""Route-level tests for the ancestor endpoint (backend B2.4).

The walk and the resolver already have service-level tests covering the graph
logic. What is left to prove here is what only a route can get wrong:

* **the ownership choke point.** The path carries a conversation id, so the
  handler cannot run without OwnedConversation having resolved it. These tests
  assert that a stranger's conversation and a stranger's message are both 404
  and not 403 - a 403 confirms the id exists.
* **serialization.** The service returns ORM objects and dataclasses; the
  response is JSON. An anchor that never reaches the client is a bug the
  service tests cannot see, because the frontend is what renders the span.
* **the query parameter.** max_depth arriving as a string from a URL, and
  being refused when out of range.
"""

from uuid import uuid4

ALICE = ("alice@example.com", "a-good-password")
BOB = ("bob@example.com", "another-password")

PARENT_TEXT = "pgvector uses HNSW indexes, which trade recall for speed."
ANCHOR_TEXT = "trade recall for speed"
ANCHOR_START = PARENT_TEXT.index(ANCHOR_TEXT)
ANCHOR_END = ANCHOR_START + len(ANCHOR_TEXT)


async def signup(client, who):
    email, password = who
    return await client.post(
        "/auth/signup", json={"email": email, "password": password}
    )


async def new_conversation(client, **body):
    response = await client.post("/conversations", json=body)
    return response.json()["id"]


async def post_message(client, conversation_id, **body):
    return await client.post(f"/conversations/{conversation_id}/messages", json=body)


async def get_ancestors(client, conversation_id, message_id, **params):
    return await client.get(
        f"/conversations/{conversation_id}/messages/{message_id}/ancestors",
        params=params,
    )


async def seeded(client, who=ALICE, default_strategy="HierarchicalDecay"):
    """A conversation with a root question, a reply, and a branch off the reply.

        root   (user: explain HNSW)
        |
        reply  (assistant: PARENT_TEXT)
        |
        branch (user, anchored on "trade recall for speed")
        |
        follow (user, plain continuation)
    """
    await signup(client, who)
    conversation_id = await new_conversation(client, default_strategy=default_strategy)

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

    branch = (
        await post_message(
            client,
            conversation_id,
            role="user",
            content="why is recall lower?",
            parent_message_id=reply["id"],
            anchor_start=ANCHOR_START,
            anchor_end=ANCHOR_END,
            anchored_text=ANCHOR_TEXT,
        )
    ).json()["message"]

    follow = (
        await post_message(
            client,
            conversation_id,
            role="user",
            content="and the cost per call?",
            parent_message_id=branch["id"],
        )
    ).json()["message"]

    return conversation_id, root, reply, branch, follow


# --- the response ------------------------------------------------------


async def test_the_chain_comes_back_nearest_first(client):
    conversation_id, root, reply, branch, follow = await seeded(client)

    response = await get_ancestors(client, conversation_id, follow["id"])
    assert response.status_code == 200

    body = response.json()
    assert [step["depth"] for step in body["steps"]] == [1, 2, 3]
    assert [step["message"]["id"] for step in body["steps"]] == [
        branch["id"], reply["id"], root["id"]
    ]
    assert body["truncated"] is False


async def test_the_anchor_survives_serialization(client):
    """The branch edge is two steps up from `follow`.

    The frontend renders the span from these three fields, so a null here is a
    real bug even though the service-level tests are green.
    """
    conversation_id, _root, _reply, _branch, follow = await seeded(client)

    body = (await get_ancestors(client, conversation_id, follow["id"])).json()

    # step 1 attached `follow` by a plain continuation
    assert body["steps"][0]["edge"]["anchored_text"] is None
    # step 2 attached the branch, so it carries the span
    assert body["steps"][1]["edge"]["anchored_text"] == ANCHOR_TEXT
    assert body["steps"][1]["edge"]["anchor_start"] == ANCHOR_START
    assert body["steps"][1]["edge"]["anchor_end"] == ANCHOR_END


async def test_the_resolved_strategy_comes_back_with_the_chain(client):
    """One round trip answers both "what is above me" and "how will I compose"."""
    conversation_id, _root, _reply, branch, _follow = await seeded(client)

    body = (await get_ancestors(client, conversation_id, branch["id"])).json()

    assert body["strategy"]["strategy"] == "SpanOnly"
    assert body["strategy"]["source"] == "branch_default"
    assert body["strategy"]["edge_id"] is not None


async def test_a_continuation_under_a_branch_reports_the_boundary(client):
    conversation_id, _root, _reply, _branch, follow = await seeded(
        client, default_strategy="ParentOnly"
    )

    body = (await get_ancestors(client, conversation_id, follow["id"])).json()

    assert body["strategy"]["strategy"] == "ParentOnly"
    assert body["strategy"]["source"] == "branch_boundary"


async def test_the_root_has_an_empty_chain(client):
    conversation_id, root, _reply, _branch, _follow = await seeded(client)

    body = (await get_ancestors(client, conversation_id, root["id"])).json()

    assert body["steps"] == []
    assert body["truncated"] is False
    assert body["strategy"]["source"] == "conversation_default"
    assert body["strategy"]["edge_id"] is None


# --- the query parameter -----------------------------------------------


async def test_max_depth_truncates(client):
    conversation_id, _root, reply, branch, follow = await seeded(client)

    body = (
        await get_ancestors(client, conversation_id, follow["id"], max_depth=2)
    ).json()

    assert [step["message"]["id"] for step in body["steps"]] == [
        branch["id"], reply["id"]
    ]
    assert body["truncated"] is True


async def test_max_depth_zero_returns_no_steps_but_still_resolves(client):
    """The strategy is not affected by max_depth - it has its own stop rule."""
    conversation_id, _root, _reply, branch, _follow = await seeded(client)

    body = (
        await get_ancestors(client, conversation_id, branch["id"], max_depth=0)
    ).json()

    assert body["steps"] == []
    assert body["truncated"] is True
    assert body["strategy"]["strategy"] == "SpanOnly"


async def test_a_negative_max_depth_is_a_422(client):
    """Refused by the query constraint, not by the ValueError in the service."""
    conversation_id, _root, _reply, _branch, follow = await seeded(client)

    response = await get_ancestors(
        client, conversation_id, follow["id"], max_depth=-1
    )
    assert response.status_code == 422


async def test_a_max_depth_past_the_safety_cap_is_a_422(client):
    conversation_id, _root, _reply, _branch, follow = await seeded(client)

    response = await get_ancestors(
        client, conversation_id, follow["id"], max_depth=5000
    )
    assert response.status_code == 422


# --- ownership and scoping ---------------------------------------------


async def test_an_unauthenticated_request_is_a_401(client):
    conversation_id, _root, _reply, _branch, follow = await seeded(client)
    await client.post("/auth/logout")

    response = await get_ancestors(client, conversation_id, follow["id"])
    assert response.status_code == 401


async def test_another_users_conversation_is_a_404(client):
    conversation_id, _root, _reply, _branch, follow = await seeded(client)

    await signup(client, BOB)

    response = await get_ancestors(client, conversation_id, follow["id"])
    assert response.status_code == 404


async def test_another_users_message_is_a_404(client):
    """Bob asks about Alice's message, through his own conversation.

    404 rather than 403: a 403 would confirm the message id is real, which is
    the fact an IDOR probe is fishing for.
    """
    _alice_conversation, _root, _reply, _branch, alice_follow = await seeded(client)

    await signup(client, BOB)
    bob_conversation = await new_conversation(client)

    response = await get_ancestors(client, bob_conversation, alice_follow["id"])
    assert response.status_code == 404


async def test_a_message_from_another_conversation_is_a_404(client):
    """Same user, wrong conversation."""
    conversation_id, _root, _reply, _branch, follow = await seeded(client)
    other = await new_conversation(client, title="second")

    response = await get_ancestors(client, other, follow["id"])
    assert response.status_code == 404


async def test_an_unknown_message_id_is_a_404(client):
    conversation_id, _root, _reply, _branch, _follow = await seeded(client)

    response = await get_ancestors(client, conversation_id, uuid4())
    assert response.status_code == 404


async def test_a_malformed_message_id_is_a_422(client):
    conversation_id, _root, _reply, _branch, _follow = await seeded(client)

    response = await client.get(
        f"/conversations/{conversation_id}/messages/not-a-uuid/ancestors"
    )
    assert response.status_code == 422
