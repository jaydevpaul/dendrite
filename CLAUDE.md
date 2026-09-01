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

## Current state (2026-09-01)

**Built:** models + Alembic migrations · `/health` · full auth
(`/auth/signup|login|logout|me`, argon2 + HS256 JWT in an HttpOnly cookie) ·
conversation routes (`POST|GET /conversations`, `GET|PATCH
/conversations/{id}`) · message + edge write layer (`POST|GET
/conversations/{id}/messages`) · 103 backend tests · frontend slices 1 and 2
(landing, signup/login, route guards, theme toggle, conversation list +
create + detail with rename) verified end to end through the Vite proxy.

**Not built:** the §8.4 ancestor walk, strategy resolution by walk-up,
generation, summarization, embeddings, eval framework, the graph navigator.

Committed through frontend slice 2 (`b7351af`, which also carries the
`70ccde22e86d` index migration). **Backend B1 is uncommitted** — `app/main.py`
plus `app/{schemas,services}/message.py`, `app/api/routes/messages.py` and
`tests/test_message_routes.py`, along with this session's doc updates.

### Running it

```
docker compose up -d                          # Docker Desktop must be running
uvicorn app.main:app --reload --port 8000     # repo root, .venv active
cd frontend && npm run dev                    # :5173
pytest                                        # repo root, 103 passing
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
  JSON, which reads like a backend bug and is not one. Nesting new routes under
  an existing prefix (as `/conversations/{id}/messages` does) sidesteps this
  entirely — a reason to prefer it, not just tidiness.
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
- **After `await session.rollback()`, treat every ORM object as empty.**
  Rollback *expires* every object in the session, so a later `obj.attr` is a
  hidden SELECT — and from an exception path in async SQLAlchemy that raises
  `MissingGreenlet`, not a clean error. Read out any value you still need
  *before* rolling back. (Cost one debugging round in B1's `_claim_root`.)
- **A CHECK constraint only ever sees the row being written.** Anything that
  has to compare against another table's row — the anchor against the parent's
  text, the parent against this conversation — is an app-layer check in the
  service, returning 422/404 rather than a 500 from an IntegrityError. The DB
  constraints stay as the backstop.
- **Capital `Conversation` is the table; lowercase `conversation` is the row
  you own.** `Message.conversation_id == Conversation.id` typechecks, runs, and
  is a tautology every row satisfies — it silently deletes the ownership guard
  and adds a cross join. This exact typo shipped once in B1.
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
**Backend B2 — the §8.4 ancestor walk.** A recursive CTE stepping up via
`edge.child_message_id`, plus **strategy resolution by walk-up** (§6: take the
message's parent edge; non-null `strategy_override` wins; else step to that
edge's parent and repeat; reach the root with no hit → `Conversation.
default_strategy`). §8.4 bounds the walk at ~depth 3 and forbids path
enumeration or a closure table pre-emptively. The write layer it reads (B1) is
built and tested.

After that, **frontend slice 3 — linear chat**, which is blocked on generation
(Layer C). Slice 3 also **moves the conversation list into a persistent left
sidebar**: the app should read like ChatGPT/Claude, with familiar linear chat
as the main surface and branching as the layer on top. Today's separate list
page is the less familiar shape; the API layer, hooks and rows carry over.

## Progress log

Full history is in **`docs/PROGRESS.md`** — this section carries only the most
recent entry. At the end of each session, append there and replace the entry
below. If a fact will still matter in three months (a port, a run command, a
standing gotcha, a working rule), promote it into **Current state** above
instead of leaving it buried in a dated entry.

- **2026-09-01**: Frontend slice 2 (conversation list) and backend B1 (message
  + edge write layer) built; tests 69 → 103. Six spec-silent questions settled
  first — nested `/conversations/{id}/messages`, one POST writing message *and*
  edge in one transaction, anchor validated against the parent's real text,
  parent must share the conversation (a plain FK otherwise lets you attach to a
  stranger's message), a second parentless message → 409, and no
  role-alternation rule. `root_message_id` is claimed by a conditional
  `UPDATE ... WHERE root_message_id IS NULL` so two concurrent first messages
  cannot both win. `conversation.updated_at` now moves on every message write,
  for the slice-3 sidebar's activity ordering. `GET .../messages` returns two
  flat lists (messages + edges), not a nested tree. Nine bugs found in
  hand-typed code, one a live security hole (`Conversation.id` for
  `conversation.id`); one bug was mine (`conversation.id` read after
  `session.rollback()` → `MissingGreenlet`). All six LOCKED-adjacent decisions
  are now written into the decision record as **§8.12**, with pointer notes on
  the three §9 rows they touch.
  **Next: backend B2** — the §8.4 recursive-CTE ancestor walk and strategy
  resolution by walk-up.
