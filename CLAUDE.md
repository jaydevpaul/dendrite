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

## Current state (2026-09-07)

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
**`HierarchicalDecay`** · **ancestor-scoped pgvector retrieval and
`HierarchicalDecayWithRetrieval` (`app/services/retrieval.py`, plus
`render_decayed()` shared out of `app/context/base.py`)** ·
**`compose_context()` and the dispatch table (`app/context/compose.py`)** ·
**the generation service (`app/services/generation.py`) — the blank-row commit,
the buffered stream, the completion write, and the `Generation` row on both the
success and failure paths** · **the streaming route (`POST
/conversations/{id}/messages/{message_id}/generate`), the four SSE events
(`app/api/sse.py`), and `MessageOut.pending`** · 337 backend tests ·
frontend slices 1, 2 and 3
(landing, signup/login, route guards, theme toggle, conversation create +
rename) · **frontend slice 3 — linear chat: the persistent conversation
sidebar, the thread, the composer, SSE streaming via `fetch` +
`ReadableStream`, and retry on an unanswered or unfinished reply
(`frontend/src/features/messages/`, `components/conversation-sidebar.tsx`, the
rewritten `app-shell.tsx` and both conversation routes)** — all verified end to
end through the Vite proxy.

**Not built:** summarization (the write side — nothing populates
`message_summary` yet), the embedding write side (nothing populates
`message_embedding` yet either), the one real OpenAI client, eval framework,
the graph navigator, span branching in the UI (frontend slice 4 — the backend
side of it is done), a markdown renderer, a strategy picker, any frontend test
runner.

**All twelve Layer C shape decisions are settled and written up as §8.15
(D1–D12); the build decisions taken since are in §8.16 (C1–C2) and §8.17
(C6–C8).** Do not re-litigate them. §8.15's D8, D9 and D11 each carry a dated
correction or narrowing from this session — read the parentheticals, not just
the headline.

**The tree is clean, committed through `555be6d`.** Three commits closed out
this work: `cddfeb3` for Layer C sittings C5-C8, `9fdf55f` for frontend slice
3, and `555be6d` for the write-ups. 337 tests passing on a clean tree.

### Running it

```
docker compose up -d                          # Docker Desktop must be running
uvicorn app.main:app --reload --port 8000     # repo root, .venv active
cd frontend && npm run dev                    # :5173
pytest                                        # repo root, 337 passing
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
- **A third way a frozen dataclass silently stops doing its job:**
  `decay = DecayFunction = TieredDecay()` is a *chained assignment*, not an
  annotation. It binds two class attributes — `decay` and, absurdly,
  `DecayFunction` — to the same instance, and neither is a dataclass field, so
  the constructor takes no `decay` at all. `self.decay.assign(...)` still works
  off the class attribute, which is why nothing raises and only a test that
  passes a tier catches it. Same family as the missing-annotation and
  misspelled-`__post_init__` traps above; this one shipped in C5.
- **A forgotten `await` on an optional-work helper disables its own fallback.**
  `query_vector = self._embed(request)` returns a coroutine, and a coroutine is
  never `None`, so `if query_vector is None:` never fires and the coroutine
  object goes into the query where the vector belongs. The failure is a
  pgvector type error pointing at the query, not at the missing keyword.
- **The pgvector distance is one expression used twice.** `.distinct(col)` must
  come before `.order_by()`, and the order-by's *first* column has to be the
  same one `DISTINCT ON` names, or Postgres rejects the statement outright. The
  ranking order is therefore not expressible in that same query — it is done in
  Python afterwards, which is also where the tie-break lives.
- **Assigning a column the value it already holds is not a change, so
  `onupdate` fires anyway.** `message.updated_at = message.created_at` looks
  like the explicit-value-wins rule working, and does nothing: the two columns
  are already equal from the insert, so the ORM sees no change, leaves the
  column out of the SET clause, and `onupdate=func.now()` supplies `now()`
  after all. The reply's `updated_at` ends up ~40ms ahead of `created_at`,
  having never been edited, and that difference is what anchor repair keys off.
  The completion write therefore names both columns in an explicit
  `update(Message).values(...)`, which cannot be optimised away. Cost one test
  failure in C7 — a passing test would have shipped it silently.
- **A wrong attribute name inside a `try` reads as a provider failure.**
  `context.message` instead of `context.messages` raised `AttributeError` from
  inside `stream_generation`'s `except Exception`, so every run took the
  failure path, wrote a failed `Generation` row and yielded `error` — and a
  test waiting for the stream to reach its gate hung forever instead of
  failing. `except Exception` around a provider call cannot tell a typo from an
  outage. A `pytest` run that *hangs* in the C7 tests means the LLM call itself
  is raising.
- **The linear thread is a *walk* over the graph, not the graph's own order.**
  `buildThread()` in `frontend/src/features/messages/thread.ts` follows
  **continuation edges only, newest child at each step**, and both halves are
  load-bearing. Continuation-only keeps anchored branches off the main path, so
  span branching cannot silently hijack the linear view. Newest-wins is what
  makes retry work: asking again writes a *second* assistant child of the same
  question rather than replacing the first, so the new attempt becomes the path
  and the abandoned one drops off it — reported on the question as "1 earlier
  reply not shown here". Change either half and retry stops being visible or
  branches start stealing the thread; neither fails loudly.
- **The fake finishes faster than a client can abandon a stream.** `curl -m
  0.05` against `/generate` disconnects and the server *still* completes the
  write, because the reply is already collected by then — so a blank
  `pending` assistant row cannot be produced that way. To exercise that state,
  insert the blank message and its edge into the dev database directly.
- **An email in the `.test` TLD is a 422, not a signup.** `email-validator`
  rejects special-use and reserved domains, so manual verification through the
  proxy needs an ordinary-looking domain. The failure reads as a broken signup
  route and is not one.
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
**Layer C — generation, sitting C9.** Every shape decision is settled in
**§8.15 (D1–D12)**, with the build decisions in **§8.16** and **§8.17**; read
those first and do not re-litigate them. Streaming is SSE via
`StreamingResponse`, not websockets (§8.8).

The nine sittings, in dependency order — each is one hand-typing session:

| # | Piece | Needs | State |
|---|---|---|---|
| C1 | `LLMClient` protocol, `FakeLLMClient`, LLM config keys | nothing | **done** |
| C2 | Context types, strategy interface, `FullInheritance`, `ParentOnly`, `SpanOnly` | the B2 walk | **done** |
| C3 | Decay function interface + `TieredDecay` + the summary reader | DB | **done** |
| C4 | `HierarchicalDecay` | C3 | **done** |
| C5 | Ancestor-scoped pgvector retrieval + `HierarchicalDecayWithRetrieval` | C4 | **done** |
| C6 | `compose_context()` — resolve → walk → dispatch → degradations | C2–C5 | **done** |
| C7 | Generation service — §8.14's write pattern, the `Generation` row, the failure path | C6 | **done** |
| C8 | SSE route, the four events, `MessageOut.pending` | C7 | **done** |
| **C9** | The one concrete OpenAI client, against the real API | last, on purpose | **next** |

C9 is deliberately last: everything above it is testable against the fake with
no key and no spend.

**C9 concretely:** one class satisfying `LLMClient` against the real OpenAI
API. `generate` streams and must finish with exactly one `Completed` carrying
the provider's own `usage` — for chat completions that needs
`stream_options={"include_usage": True}` in the request, or no usage arrives at
all and every `Generation` row lands with null token counts. `embed` returns
1536 floats from `text-embedding-3-small`. Model ids, `base_url` and the effort
dial are already in config; set `DENDRITE_LLM_CLIENT=openai` and
`DENDRITE_LLM_API_KEY` in `.env` to switch `get_llm()` over.

Everything above C9 is already tested against the fake, so the only new risk is
the wire format. Two things to keep: thinking stays on and held constant across
all five arms, and token counts come from the provider's `usage`, never a local
tokenizer.

**Frontend slice 4 — span branching — is now unblocked and is the alternative
to C9.** Slice 3 shipped, so linear chat is the main surface and the sidebar
holds the list; the edge and anchor routes slice 4 needs have been done since
the message layer. Two things slice 3 left on the table for it: there is still
no markdown renderer, deliberately, because it is the piece that will have to
cooperate with the anchor's character offsets; and the linear walk already
counts anchored children per message without rendering them, which is the hook
slice 4 renders into.

Pick by whether a key is available — C9 is the only remaining piece that costs
money to test.

## Progress log

Full history is in **`docs/PROGRESS.md`** — this section carries only the most
recent entry. At the end of each session, append there and replace the entry
below. If a fact will still matter in three months (a port, a run command, a
standing gotcha, a working rule), promote it into **Current state** above
instead of leaving it buried in a dated entry.

- **2026-09-07 (second session)**: **Frontend slice 3 built — linear chat, and
  the conversation list became a persistent sidebar.** No backend file changed;
  the suite stayed at **337 passing**. New: `frontend/src/features/messages/`
  (`api.ts`, `queries.ts`, `stream.ts`, `thread.ts`, `use-chat.ts`,
  `message-turn.tsx`, `composer.tsx`), `components/conversation-sidebar.tsx`,
  `components/ui/textarea.tsx`, `postStream()` in `lib/api.ts`; rewritten:
  `components/app-shell.tsx`, `routes/conversation.tsx` (the thread) and
  `routes/conversations.tsx` (`/app` is now "start a conversation", since the
  list moved into the shell). No `vite.config.ts` change — all three routes
  nest under `/conversations`, which the proxy already forwards.
  **Two shape decisions, both asked before building.** (1) **The linear path is
  continuation edges only, newest child at each step** — now a standing gotcha
  above, because both halves are load-bearing and neither fails loudly. (2)
  **An unanswered question or an unfinished reply gets an explicit button, and
  nothing generates on mount** — reopening a thread whose generation keeps
  failing would otherwise call the model every time, which with a real key is
  real spend.
  **The stream:** `fetch` + `ReadableStream` because the reply comes from a
  `POST` and `EventSource` is GET-only; decode with `stream: true`, split on
  the blank line, normalise CRLF, `JSON.parse` each `data:`, ignore unknown
  event names, cancel the body in a `finally`. `postStream` checking
  `response.ok` is meaningful because every status-code failure lands before
  the first byte. **On `done` the graph is refetched *before* the live text is
  dropped** — the assistant row is blank in storage until the completion write,
  so clearing first would flash an unfinished reply. The route is **keyed on
  the conversation id**, or a reply still streaming follows the user into the
  next conversation.
  Run metadata (arm, why, model, the provider's token counts, degradations in
  `warn`) sits under each reply and is **per-session by construction** —
  nothing reads `Generation` rows back yet.
  **Verified live through the proxy on :5173, fifteen steps**, including
  regenerating the same question and watching the walk pick the new sibling
  while reporting "1 earlier reply" on the question. The unfinished-reply state
  needed a blank row inserted straight into the dev database, because the fake
  finishes faster than a client can abandon it — also promoted to a gotcha.
  `npm run build` clean, `conversation` its own 17.4 kB chunk.
  **Flagged, not decided:** no markdown renderer (it has to cooperate with the
  anchor's character offsets, so it waits for slice 4), no frontend test runner
  (`thread.ts` is the first pure load-bearing frontend logic and the natural
  first Vitest target), no strategy picker.
  **Next: C9** (needs a key), or **frontend slice 4 — span branching**, which
  is now unblocked.
