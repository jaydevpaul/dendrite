"""Route-level tests for the conversation layer.

The load-bearing group is "ownership scoping" below. auth_design.md section 4.3
makes every conversation query filtered by user.id a hard requirement; these
tests are what stops a future refactor from quietly dropping that filter, since
the endpoints keep working perfectly for a single user either way.
"""

from uuid import uuid4

from app.models._shared import DEFAULT_STRATEGY

ALICE = ("alice@example.com", "a-good-password")
BOB = ("bob@example.com", "another-password")


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


async def create(client, **body):
    return await client.post("/conversations", json=body)


# --- create -----------------------------------------------------------


async def test_create_returns_201_with_the_locked_defaults(client):
    await signup(client, ALICE)

    response = await create(client)
    assert response.status_code == 201

    body = response.json()
    assert body["title"] == "Untitled"
    assert body["default_strategy"] == DEFAULT_STRATEGY
    # Section 9: set only once the first message exists, which is a later layer.
    assert body["root_message_id"] is None
    assert body["id"]


async def test_create_accepts_an_explicit_title_and_strategy(client):
    await signup(client, ALICE)

    response = await create(client, title="Thesis draft", default_strategy="ParentOnly")
    assert response.status_code == 201

    body = response.json()
    assert body["title"] == "Thesis draft"
    assert body["default_strategy"] == "ParentOnly"


async def test_create_strips_surrounding_whitespace_from_the_title(client):
    await signup(client, ALICE)

    response = await create(client, title="   padded   ")
    assert response.json()["title"] == "padded"


async def test_create_rejects_a_blank_title(client):
    await signup(client, ALICE)

    assert (await create(client, title="")).status_code == 422
    assert (await create(client, title="    ")).status_code == 422


async def test_create_rejects_span_only_as_a_conversation_default(client):
    """Section 5: SpanOnly is valid on branches only - a conversation has no span."""
    await signup(client, ALICE)

    assert (await create(client, default_strategy="SpanOnly")).status_code == 422


async def test_create_rejects_a_strategy_outside_the_locked_five(client):
    await signup(client, ALICE)

    assert (await create(client, default_strategy="VibesOnly")).status_code == 422


async def test_create_never_echoes_the_owner(client):
    """ConversationOut is an allowlist; user_id is the caller, not payload."""
    await signup(client, ALICE)

    response = await create(client)
    assert "user_id" not in response.json()


# --- list -------------------------------------------------------------


async def test_list_is_empty_for_a_new_user(client):
    await signup(client, ALICE)

    response = await client.get("/conversations")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_returns_newest_first(client):
    await signup(client, ALICE)
    first = (await create(client, title="first")).json()
    second = (await create(client, title="second")).json()
    third = (await create(client, title="third")).json()

    listed = (await client.get("/conversations")).json()
    assert [c["id"] for c in listed] == [third["id"], second["id"], first["id"]]


async def test_list_reorders_when_a_conversation_is_touched(client):
    """The ordering claim only holds because updated_at actually moves."""
    await signup(client, ALICE)
    first = (await create(client, title="first")).json()
    second = (await create(client, title="second")).json()

    await client.patch(f"/conversations/{first['id']}", json={"title": "bumped"})

    listed = (await client.get("/conversations")).json()
    assert [c["id"] for c in listed] == [first["id"], second["id"]]


# --- read one ---------------------------------------------------------


async def test_get_one_returns_the_conversation(client):
    await signup(client, ALICE)
    created = (await create(client, title="Thesis draft")).json()

    response = await client.get(f"/conversations/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


async def test_get_one_404s_for_an_id_that_does_not_exist(client):
    await signup(client, ALICE)

    assert (await client.get(f"/conversations/{uuid4()}")).status_code == 404


async def test_get_one_422s_on_a_malformed_id(client):
    await signup(client, ALICE)

    assert (await client.get("/conversations/not-a-uuid")).status_code == 422


# --- update -----------------------------------------------------------


async def test_patch_renames_without_touching_the_strategy(client):
    await signup(client, ALICE)
    created = (await create(client, default_strategy="ParentOnly")).json()

    response = await client.patch(
        f"/conversations/{created['id']}", json={"title": "renamed"}
    )
    assert response.status_code == 200

    body = response.json()
    assert body["title"] == "renamed"
    assert body["default_strategy"] == "ParentOnly"


async def test_patch_changes_the_strategy_without_touching_the_title(client):
    await signup(client, ALICE)
    created = (await create(client, title="Thesis draft")).json()

    response = await client.patch(
        f"/conversations/{created['id']}",
        json={"default_strategy": "HierarchicalDecayWithRetrieval"},
    )
    assert response.status_code == 200

    body = response.json()
    assert body["title"] == "Thesis draft"
    assert body["default_strategy"] == "HierarchicalDecayWithRetrieval"


async def test_patch_moves_updated_at_but_not_created_at(client):
    """The onupdate hook on Conversation.updated_at, asserted end to end."""
    await signup(client, ALICE)
    created = (await create(client)).json()

    patched = (
        await client.patch(f"/conversations/{created['id']}", json={"title": "new"})
    ).json()

    assert patched["updated_at"] > created["updated_at"]
    assert patched["created_at"] == created["created_at"]


async def test_patch_with_an_empty_body_changes_nothing(client):
    await signup(client, ALICE)
    created = (await create(client)).json()

    response = await client.patch(f"/conversations/{created['id']}", json={})
    assert response.status_code == 200
    assert response.json() == created


async def test_patch_treats_an_explicit_null_as_leave_alone(client):
    """Neither column is nullable, so null cannot mean "clear it"."""
    await signup(client, ALICE)
    created = (await create(client, title="keep me")).json()

    response = await client.patch(
        f"/conversations/{created['id']}", json={"title": None}
    )
    assert response.status_code == 200
    assert response.json()["title"] == "keep me"


async def test_patch_rejects_span_only(client):
    await signup(client, ALICE)
    created = (await create(client)).json()

    response = await client.patch(
        f"/conversations/{created['id']}", json={"default_strategy": "SpanOnly"}
    )
    assert response.status_code == 422


async def test_patch_404s_for_an_id_that_does_not_exist(client):
    await signup(client, ALICE)

    response = await client.patch(f"/conversations/{uuid4()}", json={"title": "x"})
    assert response.status_code == 404


# --- ownership scoping (auth_design.md section 4.3) --------------------


async def test_list_never_leaks_another_users_conversations(client):
    await signup(client, ALICE)
    await create(client, title="alice's secret")

    await signup(client, BOB)
    assert (await client.get("/conversations")).json() == []

    await create(client, title="bob's own")
    listed = (await client.get("/conversations")).json()
    assert [c["title"] for c in listed] == ["bob's own"]


async def test_get_one_404s_on_another_users_conversation(client):
    """The IDOR case: Bob has the exact id and still must not read the row.

    404 rather than 403 - a 403 would confirm the id is real.
    """
    await signup(client, ALICE)
    alices = (await create(client, title="alice's secret")).json()

    await signup(client, BOB)
    response = await client.get(f"/conversations/{alices['id']}")

    assert response.status_code == 404
    assert "alice" not in response.text


async def test_patch_404s_on_another_users_conversation(client):
    await signup(client, ALICE)
    alices = (await create(client, title="alice's secret")).json()

    await signup(client, BOB)
    response = await client.patch(
        f"/conversations/{alices['id']}", json={"title": "bob was here"}
    )
    assert response.status_code == 404

    # And the write must not have landed.
    await login_as(client, ALICE)
    assert (await client.get(f"/conversations/{alices['id']}")).json()[
        "title"
    ] == "alice's secret"


# --- authentication ---------------------------------------------------


async def test_every_conversation_route_requires_a_session(client):
    some_id = uuid4()
    unauthenticated = [
        client.get("/conversations"),
        client.post("/conversations", json={}),
        client.get(f"/conversations/{some_id}"),
        client.patch(f"/conversations/{some_id}", json={"title": "x"}),
    ]

    for request in unauthenticated:
        assert (await request).status_code == 401
