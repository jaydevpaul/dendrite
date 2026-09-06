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
- **No spec citations in anything the user reads while coding** — not `§8.15`,
  not `D4`, not sitting names like `C7`, in code comments, docstrings or chat
  prose. State the actual reason in a plain sentence instead. He does not open
  the docs mid-session, so a pointer is noise where a sentence would do. Cite a
  section only when he asks where something is written down. (Applies to code
  written from 2026-09-05 on; `tests/test_llm_fake.py` predates it.)

## Current state (2026-09-06)

**Built:** models + Alembic migrations · `/health` · full auth
(`/auth/signup|login|logout|me`, argon2 + HS256 JWT in an HttpOnly cookie) ·
conversation routes (`POST|GET /conversations`, `GET|PATCH
/conversations/{id}`) · message + edge write layer (`POST|GET
/conversations/{id}/messages`) · **the §8.4 ancestor walk and strategy
resolution by walk-up** (`app/services/ancestors.py`, `GET
/conversations/{id}/messages/{message_id}/ancestors`) · **the LLM seam
(`app/llm/base.py`, `app/llm/fake.py`, the seven LLM config keys)** · **context
composition for four of the five strategies (`app/context/base.py`,
`app/context/strategies.py`)** · **the decay function and the summary reader
(`Fidelity` + `DecayFunction` in `app/context/base.py`, `TieredDecay` in
`app/context/decay.py`, `load_summaries()` in `app/services/summary.py`)** ·
**`HierarchicalDecay`** · 250 backend tests · frontend slices 1 and 2
(landing, signup/login, route guards, theme toggle, conversation list + create +
detail with rename) verified end to end through the Vite proxy.

**Not built:** summarization (the write side — nothing populates
`message_summary` yet), embeddings, `HierarchicalDecayWithRetrieval`,
`compose_context()`, the generation service and its SSE route, the one real
OpenAI client, eval framework, the graph navigator.

**All twelve Layer C shape decisions are settled and written up as §8.15
(D1–D12).** Do not re-litigate them.

Committed through `2984a1c` — C4 and its write-up. **Working tree clean**,
250 passing.

### Running it

```
docker compose up -d                          # Docker Desktop must be running
uvicorn app.main:app --reload --port 8000     # repo root, .venv active
cd frontend && npm run dev                    # :5173
pytest                                        # repo root, 250 passing
```

**Run pytest as `.venv/Scripts/python.exe -m pytest`** if the venv is not
active — the global Python 3.14 on PATH has no pytest, and `python -m pytest`
there fails with "No module named pytest", which reads like a broken install
and is not one. **Docker Desktop is installed under
`%LOCALAPPDATA%\Programs\DockerDesktop`, not `Program Files`.** With the daemon
down, every DB-backed test errors with `ConnectionRefusedError [WinError 1225]`
at connect time — that is a stopped container, never an application bug.

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
- **The same typo on a model attribute is worse, because nothing raises.**
  `Anchor.from_edge` was typed as `Edge.anchor_start` instead of
  `edge.anchor_start` — the class, not the row it was handed. It typechecks,
  it runs, and it puts `(<class 'int'>, <InstrumentedAttribute ...>)` into the
  composed prompt where the highlighted text belongs. The model receives
  SQLAlchemy internals and no error is raised anywhere. Cost one round in C2.
- **Two ways a frozen dataclass silently stops doing its job.** A field with no
  type annotation (`full_depth = 3` instead of `full_depth: int = 3`) is not a
  field at all — it is a plain class attribute, the generated `__init__` takes
  no arguments, and `TieredDecay(full_depth=1)` dies with "unexpected keyword
  argument". The tier stops being swappable, which is the only reason it is a
  constructor argument. Worse, `__post_init__` misspelled with one leading
  underscore is simply never called, so every validation in it disappears with
  no error anywhere — `TieredDecay(full_depth=-1)` builds happily and
  summarizes the whole chain. Both shipped in C3 and neither raised.
- **A two-field frozen dataclass has to declare its tuning argument first.**
  `HierarchicalDecay` declares `decay` before `name`, so
  `HierarchicalDecay(TieredDecay(full_depth=1))` sets the decay. Declared the
  other way round — the way the three single-field strategies look — that same
  call puts a `TieredDecay` instance into `name` and leaves the tier at its
  default. `AnyStrategy` is a `Literal` hint and is not checked at runtime, so
  nothing raises; the junk value surfaces later in `generation.strategy_used`.
- **Postgres `btrim` trims spaces only unless you name the characters.**
  `btrim("  \n  ")` returns `"\n"`, which is not empty, so a whitespace-only
  summary passes an `!= ""` test. The reader spells the set out:
  `func.btrim(col, " \t\r\n") != ""`. The SQL is well-formed and the query
  runs either way — the code just quietly disagrees with you about what "blank"
  means, and only a whitespace test catches it.
- **A misplaced closing paren turns a query into a tuple, not a syntax error.**
  `select(...).where(a), b` builds `(select, boolean)`, and the failure lands
  later as `AttributeError` on a tuple at the next `.where()` or `.distinct()`,
  pointing at the wrong line.
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
**Layer C — generation, sitting C5.** Every shape decision is settled in
**§8.15 (D1–D12)**; read that first and do not re-litigate it. Streaming is SSE
via `StreamingResponse`, not websockets (§8.8).

The nine sittings, in dependency order — each is one hand-typing session:

| # | Piece | Needs | State |
|---|---|---|---|
| C1 | `LLMClient` protocol, `FakeLLMClient`, LLM config keys | nothing | **done** |
| C2 | Context types, strategy interface, `FullInheritance`, `ParentOnly`, `SpanOnly` | the B2 walk | **done** |
| C3 | Decay function interface + `TieredDecay` + the summary reader | DB | **done** |
| C4 | `HierarchicalDecay` | C3 | **done** |
| **C5** | Ancestor-scoped pgvector retrieval + `HierarchicalDecayWithRetrieval` | C4 | next |
| C6 | `compose_context()` — resolve → walk → dispatch → degradations | C2–C5 | |
| C7 | Generation service — §8.14's write pattern, the `Generation` row, the failure path | C6 | |
| C8 | SSE route, the four events, `MessageOut.pending` | C7 | |
| C9 | The one concrete OpenAI client, against the real API | last, on purpose | |

C9 is deliberately last: everything above it is testable against the fake with
no key and no spend.

**C5 concretely:** ancestor-scoped pgvector retrieval, then
`HierarchicalDecayWithRetrieval` in `app/context/strategies.py`. The shape is
settled in §8.15 D6 and should not be re-argued: decay runs **first**, then
retrieval re-marks some steps that decay marked `summary` back to `full`, **in
place** — never appended as a separate excerpts block, which would send the same
message twice. Retrieval therefore only ever considers already-summarized steps,
so it does nothing on a chain short enough that nothing was summarized, and it
can never undo the full-fidelity tier.

How many get promoted is a fraction of the summarized count, not a fixed k:
`min(ceil(fraction * n_summarized), max_promotions)`, with `fraction = 1/3` and
`max_promotions = 10`. Both are constructor arguments so the eval can sweep
them. The query is scoped by the walk's ancestor ids **and** filtered on
`model_used`, and the query text is the user's message plus the anchored span.
That `embed` call is the only network call in compose, so it is where §8.6's
timeout and fallback live. No similarity threshold in MVP.

Also still open before the eval: **nothing has embedded anything yet**, the same
way nothing had summarized anything before C4 — expect the same
degrade-and-report shape, and check whether the missing-embedding case needs its
own degradation name alongside `SUMMARY_MISSING`.

After Layer C, **frontend slice 3 — linear chat**. Slice 3 also **moves the
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

- **2026-09-06**: **C4 built — `HierarchicalDecay`**, plus a correction to
  C3's summary reader. Suite is **250 passing**, up from 230. Assembly as
  planned: nothing new was invented, and `Fidelity`, `DecayFunction`,
  `TieredDecay`, `load_summaries()`, `summarised_turn()` and `SUMMARY_MISSING`
  came from C3 unchanged.
  **The strategy** assigns fidelities over the whole walk, collects the ids
  marked `summary`, makes one `load_summaries()` call, then renders
  nearest-first-reversed into prompt order with `full_turn` or
  `summarised_turn`. `SUMMARY_MISSING` is a boolean set in the loop and
  appended **once** after it — four short levels is one finding about one
  compose, and the eval reports a rate per run. Severity is not lost, since
  `composed_context` stores the payload and a later pass can count which turns
  beyond the tier lack the marker. `walk_truncated` **does** apply here, unlike
  `ParentOnly` and `SpanOnly`, because this arm climbs to the root. Order when
  both fire is `[walk_truncated, summary_missing]`.
  **`decay` is declared before `name`** so the positional form sets the decay;
  the other way round it would land in `name` with nothing raising. Now a
  standing gotcha above.
  **23 new tests** in `tests/test_context_strategies.py`, built on
  `a_deep_branch()` (seven ancestors, depths 1–7) with a `summarised` argument
  selecting "older", "none" or "all". Query counts are pinned at **zero** for a
  chain inside the tier and **one** for a deep chain. The cross-strategy block
  now runs against `BUILT_STRATEGIES`, so all four arms answer for one system
  preamble, one identical final question turn, and naming themselves.
  `counting_queries` moved into `tests/conftest.py`.
  **C3's reader now excludes blank summaries in the `WHERE`** —
  `func.btrim(summary_text, " \t\r\n") != ""`. A blank summary is the message
  gone, not a cheaper version of it, and it has to be excluded in the query
  rather than dropped from the map afterwards: `DISTINCT ON` keeps only the
  newest row, so a blank written today wins on recency and takes a good older
  summary down with it. **Written up in §8.16**, which also picked up the
  `created_at DESC, id DESC` correction and closed §12's "current summary
  selection rule" item. Two `btrim` and paren gotchas from it are now standing
  gotchas above.
  **Two decay variants considered and rejected.** Linear and exponential
  collapse to a single cutoff depth while `Fidelity` has only two levels, so all
  three would produce identical prompts; they need *graded* fidelity, which
  needs a §9 change. A fractional tier (`ceil(len/3)`) does differ, but it makes
  arm 4's token cost depend on fixture depth — the comparability D5 protected by
  choosing depth over token budget — and sweeping `full_depth` gets most of it.
  **Open item raised against §7: hyperparameter selection is unspecified.**
  Arm 4 has one tunable knob and arm 5 has three, against zero for the three
  baselines. Sweeping on the scenarios the results are reported from gives the
  tuned arms N attempts to the baselines' one. Likely answer is a
  tuning/reporting split (~8 of the 20–30 scenarios held back for sweeping, the
  rest run once). Not settled — logged as a §12 open item, triggered on "before
  the eval harness is built".
  **Next: sitting C5** — ancestor-scoped pgvector retrieval and
  `HierarchicalDecayWithRetrieval`.
