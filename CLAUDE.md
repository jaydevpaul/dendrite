# Dendrite

Graph-aware context composition for branching AI chat. Users branch from a
highlighted span inside an AI response; the child branch receives a
hierarchically composed context (span full, parent full, older ancestors
decaying to summaries with retrieval drill-down). Evaluated against baselines
on quality-per-token.

**Authoritative spec:** `docs/Dendrite_Decision_Record.md`. Treat it as the
single source of truth. Do NOT re-litigate anything marked LOCKED there — if a
locked decision genuinely needs changing, say so and we write a superseding
record; never pivot silently.

## Stack (locked)
- Python + FastAPI
- Postgres + pgvector (single system; no separate vector store)
- SQLAlchemy for models
- UUID v7 primary keys everywhere
- Async summarization via arq (or FastAPI BackgroundTasks); not Celery
- Embeddings: text-embedding-3-small → vector(1536), cosine distance

## Data model (six entities)
Conversation, Message, Edge, Generation, MessageSummary, MessageEmbedding.
Full field-level schema, constraints, and indexes are in **section 9** of the
decision record. Key rules: message-as-node (not turn); Edge carries the
parent→child link and is immutable in topology (no re-parenting); anchor fields
populated → branch, null → continuation; regeneration never deletes.

## Working rules for this repo
- One layer at a time. Do NOT scaffold the whole app in a single session.
- Follow the locked schema exactly — types, nullability, CHECK constraints, and
  indexes as specified in section 9. Do not "improve" them without flagging.
- If the spec is ambiguous or silent on something, ask / flag it rather than
  inventing a decision.
- **Backend (`app/`): the user hand-types every line** to learn it — present
  code in chat, do not edit those files. **Frontend (`frontend/`), `tests/` and
  docs: write directly.**
- A frontend slice may not begin before the backend capability it renders
  exists (decision record §8.10).

## Current state (2026-08-31)

**Built:** models + Alembic migrations · `/health` · full auth
(`/auth/signup|login|logout|me`, argon2 + HS256 JWT in an HttpOnly cookie) ·
conversation routes (`POST|GET /conversations`, `GET|PATCH
/conversations/{id}`) · 69 backend tests · frontend slice 1 (landing,
signup/login, route guards, theme toggle) verified end to end through the
Vite proxy.

**Not built:** message + edge routes, the §8.4 ancestor walk, generation,
summarization, embeddings, eval framework, the graph navigator.

Everything through the conversation layer is committed (`37951c6`).

### Running it

```
docker compose up -d                          # Docker Desktop must be running
uvicorn app.main:app --reload --port 8000     # repo root, .venv active
cd frontend && npm run dev                    # :5173
pytest                                        # repo root, 69 passing
```

**The DB is on host port 5433, not 5432.** A native Windows Postgres service
keeps reclaiming 5432 and it *also* has a `dendrite` role and database, so a
wrong port connects successfully into an empty schema instead of failing —
Alembic's "target database is not up to date" was the only symptom. `.env`
exists locally (gitignored) and **overrides code defaults**, so a stale port
there silently re-breaks the connection.

### Standing gotchas

- **Always review Alembic autogenerate output.** It has needed hand-correction
  3 times out of 4: missing `pgvector` import, no `CREATE EXTENSION vector`,
  the `use_alter` circular FK silently dropped, and unnamed constraints that
  make `downgrade()` unrunnable. `metadata.create_all` handles the circular FK;
  Alembic does not. (The clean one, `70ccde22e86d`, was a bare `create_index`
  touching neither the vector column nor the circular FK — the two things it
  gets wrong.)
- **Never add CORS middleware, never weaken the cookie to `SameSite=None`.**
  The Vite proxy makes both unnecessary. See `frontend_design.md` §3 — the
  half-configured-CORS failure mode is silent. **Every new route prefix needs
  its own proxy entry** in `vite.config.ts` (`/auth`, `/health`,
  `/conversations` → :8000); miss one and Vite returns `index.html` instead of
  JSON, which reads like a backend bug and is not one.
- **Every conversation query goes through `app/services/conversation.py`.**
  `get_owned_conversation()` is the single ownership choke point, and the
  `OwnedConversation` dependency in the routes means a handler cannot obtain a
  `Conversation` without the `user_id` filter having run. Do not write a bare
  `select(Conversation)` in a route. Unowned rows return **404, not 403** — a
  403 confirms the id exists, which is what an IDOR probe is fishing for.
- **`onupdate=` is SQLAlchemy-side and generates no DDL** — no migration, and
  autogenerate correctly sees nothing. It only fires on UPDATEs SQLAlchemy
  emits, not on raw SQL. (`server_onupdate=` merely *asserts* a trigger exists;
  it does not create one.)
- Do not pipe a backgrounded dev server through `tail` — it buffers and the log
  stays empty.
- Anything rendered on the frontend's fixed-dark brand panel needs a
  `tone="panel"` variant, or it breaks in light mode.

## Companion docs

- `docs/Dendrite_Decision_Record.md` — authoritative spec; wins over everything.
- `docs/auth_design.md` — auth architecture, threat model, flows.
- `docs/frontend_design.md` — frontend stack, **locked palette** (§5), slice order.
- `docs/PROGRESS.md` — full session history. Read on demand.

## Next task
**Frontend slice 2 — conversation list** (`frontend_design.md` §8: list,
create, empty state). Unblocked as of 2026-08-31; the conversation routes it
renders now exist. Remember the `/conversations` proxy entry.

After that, **backend Layer B: message + edge routes and the §8.4
recursive-CTE ancestor walk** — message create/list, `root_message_id` set on
the first message, Edge creation (anchors → branch, null → continuation, the §9
CHECK constraints have never been exercised), and strategy resolution by
walk-up. Note that message creation without generation is a partial feature:
nothing composes context or calls a model until Layer C.

## Progress log

Full history is in **`docs/PROGRESS.md`** — this section carries only the most
recent entry. At the end of each session, append there and replace the entry
below. If a fact will still matter in three months (a port, a run command, a
standing gotcha, a working rule), promote it into **Current state** above
instead of leaving it buried in a dated entry.

- **2026-08-31 (session close)**: Backend conversation layer built, tested and
  committed (`37951c6`); frontend slice 2 is now unblocked.
  - **Routes**: `POST /conversations`, `GET /conversations`,
    `GET|PATCH /conversations/{id}`. No DELETE — deferred to `ROADMAP.md`.
  - **Ownership is structural, not remembered.** All queries live in
    `app/services/conversation.py`; the `OwnedConversation` FastAPI dependency
    means a route body cannot get a `Conversation` without the `user_id` filter
    having run. Unowned rows → **404, not 403**.
  - **`updated_at` now moves**: `onupdate=func.now()` on Conversation and
    Message. It had never been set, so the column was frozen at insert and any
    "newest first" ordering would have silently sorted by creation time. **No
    migration** — `onupdate` is SQLAlchemy-side and emits no DDL.
  - **Strategies are now `Literal` types** (`AnyStrategy`, `NonSpanStrategy` in
    `app/models/_shared.py`), with the tuples derived via `get_args` and a
    runtime drift guard. One source drives both the SQL CHECK constraints and
    the Pydantic schemas, and OpenAPI gets a real enum for slice 6's strategy
    picker. Values and order unchanged, so the CHECK SQL is byte-identical.
  - **Tests 45 → 69** (`tests/test_conversation_routes.py`, 24 new). The
    ownership group is the load-bearing one; `test_patch_404s_on_another_users
    _conversation` also re-reads as the owner to prove the rejected write never
    landed, since a status-code-only assertion would pass either way.
  - **`ROADMAP.md` created** — first entry is `AdaptiveBudget`, the user's
    "fill the window if it fits, decay only when it doesn't" idea, recorded as
    an **eval hypothesis with a trigger** rather than built. Rejected as a
    default for three reasons: the metric is quality *per token*, so spending
    because there is room is the wastes-tokens half of the §1 binary; branch
    context that merely *fits* is still distractor context and contradicts the
    span anchor; and an adaptive strategy blurs the eval by behaving as
    `FullInheritance` on short conversations. Also: §8.4 bounds the ancestor
    walk at ~depth 3, so at MVP scale it would resolve to `FullInheritance`
    nearly always — shipping the naive baseline as the product default.
  - **`DEFAULT_STRATEGY = "HierarchicalDecayWithRetrieval"`** (user's call). §5
    and §9 are both silent on what a new conversation gets. Chosen as the full
    thesis; §8.6 already specifies degrading to `HierarchicalDecay` when the
    embedding service is unavailable, which is the state of the world until the
    embedding pipeline exists. **Not yet in the decision record** — see the
    LOCKED questions raised at session close.
  - **`.gitattributes` added** (`* text=auto eol=lf` + binary rules). Line
    endings were a per-machine `core.autocrlf` fact; now a repo fact. Verified
    a no-op for existing content — `git ls-files --eol` showed everything
    already stored as LF.
  - **Two bugs caught reviewing hand-typed code**: an inverted drift guard in
    `_shared.py` (`==` where `!=` was meant, so the module raised on *success*
    and nothing imported), and `response_model=list[Conversation]` on the list
    route — the SQLAlchemy model, not `ConversationOut`. The second mattered
    twice: FastAPI rejects it at decoration time, *and* `ConversationOut` is the
    allowlist keeping `user_id` out of responses, so the list endpoint was the
    one route that had escaped it.
  - **Next: frontend slice 2** (conversation list), then backend Layer B —
    message + edge routes and the §8.4 ancestor walk.
