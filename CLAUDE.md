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

## Current state (2026-09-03)

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

**All twelve Layer C shape decisions are settled and written up as §8.15
(D1–D12).** Do not re-litigate them. `tests/test_llm_fake.py` is already written
and waiting for C1's code.

Everything is committed, through `9c3108b`. The working tree is clean.

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
- **Compose from the *user* message, never from the blank assistant row.**
  §8.14 inserts a blank assistant message before streaming, and it is tempting
  to walk from *that*. Doing so puts the anchored branch edge at depth 2, where
  §8.13's rule answers with `Conversation.default_strategy` instead of
  `SpanOnly`. No error and no exception — every branch silently resolves to the
  wrong strategy, branching stops working, and §7 reports five strategies while
  comparing four. Resolve and walk from the user message, *before* the blank row
  is inserted (§8.15 D2).
- **SSE frames are newline-delimited, so chunk text must be JSON-encoded.** A
  bare newline inside `data:` ends the frame, and model output is full of them —
  the failure presents as the model producing broken markdown, not as a
  transport bug (§8.15 D10). Related: the stream comes back from a `POST`, so
  the browser's `EventSource` (GET only) cannot read it — `fetch()` plus a
  `ReadableStream` reader.
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
**Layer C — generation, sitting C1.** Every shape decision is settled in
**§8.15 (D1–D12)**; read that first and do not re-litigate it. Streaming is SSE
via `StreamingResponse`, not websockets (§8.8).

The nine sittings, in dependency order — each is one hand-typing session:

| # | Piece | Needs |
|---|---|---|
| **C1** | `LLMClient` protocol, `FakeLLMClient`, LLM config keys | nothing |
| C2 | Context types, strategy interface, `FullInheritance`, `ParentOnly`, `SpanOnly` | the B2 walk |
| C3 | Decay function interface + `TieredDecay` + the summary reader | DB |
| C4 | `HierarchicalDecay` | C3 |
| C5 | Ancestor-scoped pgvector retrieval + `HierarchicalDecayWithRetrieval` | C4 |
| C6 | `compose_context()` — resolve → walk → dispatch → degradations | C2–C5 |
| C7 | Generation service — §8.14's write pattern, the `Generation` row, the failure path | C6 |
| C8 | SSE route, the four events, `MessageOut.pending` | C7 |
| C9 | The one concrete OpenAI client, against the real API | last, on purpose |

C9 is deliberately last: everything above it is testable against the fake with
no key and no spend.

**C1 concretely:** hand-type `app/llm/base.py` (the `LLMClient` protocol,
`PromptMessage`, `TextDelta`, `Completed`) and `app/llm/fake.py`
(`FakeLLMClient`, `fake_vector`, `EMBEDDING_DIMENSIONS`), plus the LLM keys in
`app/core/config.py`. **`tests/test_llm_fake.py` is already written** (28 tests)
— it is the spec for the two modules, so read it before typing. Then
`pytest tests/test_llm_fake.py`. No database, no network.

Two things the fake must get right, both load-bearing for C2–C6: it **records
every prompt it was handed** (that recording is the only proof a strategy
composed correctly), and its embeddings **bucket words rather than hashing the
whole string**, so similar text really is nearer under cosine distance — a
whole-string hash would scatter near-identical sentences and every retrieval
test would assert on noise while appearing to pass.

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

- **2026-09-03**: **Layer C decided, nothing built in `app/`.** Deliberate —
  §8.12 and §8.13 were settled before B1 and B2 and both saved rework, so Layer
  C got the same treatment. Output: **§8.15 (D1–D12)** in the decision record,
  pointer notes on §5 and three §9 rows, one §12 item struck through as resolved
  and one narrowed, `tests/test_llm_fake.py` (28 tests), and two `ROADMAP.md`
  corrections.
  **§12's in-flight-generation item is closed by deriving, not storing (D1)** —
  `MessageOut.pending` = `role == "assistant" and content == ""`, which works
  only because §8.12 made the API refuse empty `content`. A `status` column was
  rejected: a LOCKED §9 migration for something derivable, which *also* fails
  its own headline case (a process dying mid-stream runs no handler, so the
  column sticks at `'generating'` exactly as a blank row does).
  **Two recommendations were reversed on push-back, both correctly.** The prompt
  shape went from one text envelope to **real multi-turn** (D3) once it was
  pointed out that a summarized ancestor can keep its original role with a
  `[summarised]` marker — and multi-turn then also wins on caching, since
  separate turns form a byte-identical growing prefix. And **thinking stays on**
  (D11): thinking tokens scaling with input size is the *treatment's effect*,
  not a confound, so switching it off would have understated the thesis rather
  than cleaning up the metric.
  **Retrieval promotes a fraction, not a fixed k (D6).** `k = 10` would promote
  *every* summary on any chain shallower than depth 13 — six exchanges under
  message-as-node — making arm 5 byte-identical to `FullInheritance` on most of
  §7's fixtures. `min(ceil(n_summarized / 3), 10)` makes that impossible.
  **§8.14's `updated_at` claim was off by one write (D8)** — `onupdate` fires on
  the completion UPDATE, so the fix is `message.updated_at = message.created_at`
  in that same UPDATE. Not a reopening; buffer-and-write-once stands.
  **A trap caught before typing, now a standing gotcha:** composing from the
  blank assistant row puts the anchored edge at depth 2, where §8.13 answers
  with the conversation default instead of `SpanOnly` — branching would silently
  stop working.
  **Model settled (D11):** OpenAI throughout — `gpt-5.6-luna` (`effort: low`)
  generating, `gpt-5.6-terra` judging, `text-embedding-3-small` embedding. ~$13
  for the whole eval phase against ~$75 on Claude; the deciding number was
  marginal, not total — $2.59 per extra eval run versus $14.15.
  **One process lesson.** Two research agents burned ~25 min and ~335k tokens
  pricing models, only to confirm every candidate runs the eval for under a
  dollar. The back-of-envelope arithmetic had already been done *in the same
  session* and was the whole answer. When a rough number shows the decision
  doesn't turn on the unknown, don't go measure the unknown.
  **Next: sitting C1** — `app/llm/base.py` and `app/llm/fake.py` plus the LLM
  config keys, against the test file that is already written.
