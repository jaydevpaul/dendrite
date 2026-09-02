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

## Current state (2026-09-02)

**Built:** models + Alembic migrations · `/health` · full auth
(`/auth/signup|login|logout|me`, argon2 + HS256 JWT in an HttpOnly cookie) ·
conversation routes (`POST|GET /conversations`, `GET|PATCH
/conversations/{id}`) · message + edge write layer (`POST|GET
/conversations/{id}/messages`) · **the §8.4 ancestor walk and strategy
resolution by walk-up** (`app/services/ancestors.py`, `GET
/conversations/{id}/messages/{message_id}/ancestors`) · 155 backend tests ·
frontend slices 1 and 2 (landing, signup/login, route guards, theme toggle,
conversation list + create + detail with rename) verified end to end through
the Vite proxy.

**Not built:** generation (Layer C), summarization, embeddings, the strategy
interface and its five implementations, the decay function, eval framework,
the graph navigator.

Everything is committed, through `b97258d`. The working tree is clean.

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
- **The two ancestor walks are the same query with different stop rules**, and
  both live in `app/services/ancestors.py`. `walk_ancestors` climbs to the
  root; `resolve_strategy` stops at the first override *or* the first branch
  edge. Both filter `message.conversation_id` **inside** the CTE, in the seed
  *and* the recursive step — filtering after the walk is too late, because by
  then it has already climbed through a foreign message into whatever is above
  it. §8.4's "~3" is a *fidelity* tier, not a query bound; the walk goes to the
  root and 200 is a runaway guard (§8.13).
- **A recursive step joined on `parent_message_id` walks *down* the tree and
  hangs.** It behaves perfectly on a straight-line chain, so only a fork
  catches it — and it does not fail cleanly: matching on the non-unique column
  fans out, and 200 levels of fan-out is a combinatorial explosion. A `pytest`
  run that *hangs* on the B2 tests means those two columns are swapped.
- **The test database is per-pytest-process** (`dendrite_test_<pid>`, created and
  dropped by the `engine` fixture). Do not go back to one shared name. Two runs
  against one database deadlock — the per-test `TRUNCATE` takes ACCESS EXCLUSIVE
  on every table while the other run holds row locks — and the *knock-on*
  failures are the dangerous part, because they read as application bugs: a
  truncate landing mid-test wipes the signed-up fixture user, so
  `response.json()["message"]` raises `KeyError`, and two runs signing up the
  same fixture email collide on `UniqueViolation`. Cost one debugging round on
  2026-09-02, on code that was correct.
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
**Layer C — generation.** The walk it reads (B2) is built and tested, and
frontend slice 3 is blocked on it. Three things it needs before any route:

- The **`LLMClient` protocol** (`generate` + `embed`) from §8.8, with one
  concrete implementation and a **`FakeLLMClient`** — the fake is what lets
  context composition be tested without network calls or spend.
- The **strategy interface** and its five implementations (§5), since
  `resolve_strategy` now answers *which* one to run but nothing implements
  them. `HierarchicalDecay` also needs the **decay function** behind its own
  interface (§5 locks it swappable) — and that is where §8.4's `~3` full-
  fidelity tier actually lives (§8.13).
- A decision on **`Message.updated_at` under streaming** — §12's open item,
  whose trigger is exactly this layer. Current lean recorded there: buffer the
  stream and write `content` once at completion.

Streaming is SSE via `StreamingResponse`, not websockets (§8.8).

After that, **frontend slice 3 — linear chat**. Slice 3 also **moves the
conversation list into a persistent left sidebar**: the app should read like
ChatGPT/Claude, with familiar linear chat as the main surface and branching as
the layer on top. Today's separate list page is the less familiar shape; the
API layer, hooks and rows carry over.

## Progress log

Full history is in **`docs/PROGRESS.md`** — this section carries only the most
recent entry. At the end of each session, append there and replace the entry
below. If a fact will still matter in three months (a port, a run command, a
standing gotcha, a working rule), promote it into **Current state** above
instead of leaving it buried in a dated entry.

- **2026-09-02**: **Backend B2 built** — the §8.4 ancestor walk, strategy
  resolution by walk-up, and a read endpoint; tests 103 → 155, in four commits
  (`34931ed`, `223012e`, `98a5ac6`, `b97258d`). Seven spec-silent or
  spec-conflicting questions settled before typing, all written into the
  decision record as **§8.13** with pointer notes on §5, §6, §8.4, §9 and a new
  §12 open item.
  Two findings mattered more than the code. **§8.4's "~3" is a fidelity tier,
  not a bound on the walk** — read as a query cap it makes `FullInheritance`
  ("the entire ancestor chain") unbuildable and collapses `HierarchicalDecay`
  into it, since nothing older would be left to summarize; the walk now climbs
  to the root with 200 as a runaway guard. And **strategy resolution never
  crosses a branch boundary**, which reconciles §5's "branches default to
  SpanOnly" with §6's walk-up: §6's own table permits null "on branches that
  accept the default", so null on a branch *means* SpanOnly while null on a
  continuation means keep climbing. `SpanOnly` is the one value never inherited
  downward (§5 locks it branch-only). Resolution returns a `source`
  (`edge` | `branch_default` | `branch_boundary` | `conversation_default` |
  `depth_cap`), because four of five outcomes answer with the conversation
  default and a test asserting only the strategy would pass for a right answer
  reached down the wrong path.
  **A deadlock cost a debugging round, on correct code.** Two `pytest` runs
  shared one `dendrite_test`, and the per-test `TRUNCATE` takes ACCESS
  EXCLUSIVE on every table; the knock-on failures were the misleading part —
  a truncate landing mid-test wipes the fixture user, so
  `response.json()["message"]` raises `KeyError` and reads as a bug in
  `create_message`. Each run now builds `dendrite_test_<pid>`.
  Only two bugs in hand-typed code this time, both spelling (`messsage`,
  `StrategyReolution`) — Python named both in the error text. `StrategySource`
  moved to `app/models/_shared.py` so the response schema stops importing from
  a service.
  **Next: Layer C (generation)** — the `LLMClient` protocol and its fake, the
  five strategy implementations, the decay function, and §12's
  `Message.updated_at`-under-streaming decision, whose trigger is this layer.
  **Next: backend B2** — the §8.4 recursive-CTE ancestor walk and strategy
  resolution by walk-up.
