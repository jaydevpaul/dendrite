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
(landing, signup/login, route guards, theme toggle) · **frontend slice 3 —
linear chat: the persistent conversation sidebar, the thread, the composer, SSE
streaming via `fetch` + `ReadableStream`, retry on an unanswered or unfinished
reply, `StartPane` for an empty conversation, and a title derived from the
first message (`frontend/src/features/messages/`,
`components/conversation-sidebar.tsx`, the rewritten `app-shell.tsx`,
`routes/new-conversation.tsx` and `routes/conversation.tsx`)** — all verified
end to end through the Vite proxy.

**Not built:** summarization (the write side — nothing populates
`message_summary` yet), the embedding write side (nothing populates
`message_embedding` yet either), the one real OpenAI client, eval framework,
the graph navigator, span branching in the UI (frontend slice 4 — the backend
side of it is done), a markdown renderer, a strategy picker, any frontend test
runner.

**All twelve Layer C shape decisions are settled and written up as §8.15
(D1–D12); the build decisions taken since are in §8.16 (C1–C2) and §8.17
(C6–C8).** Do not re-litigate them. §8.15's D8, D9 and D11 each carry a dated
correction or narrowing — read the parentheticals, not just the headline.

**§8.18 settles two frontend shape questions** that slice 3 forced: which path
the linear view walks (continuation edges only, newest child — the standing
gotcha below says why both halves matter), and that the branch navigator now
lives in a **right-hand panel behind a switch**, because the left sidebar holds
the conversation list. The palette gained one token, `scrim`, recorded as a
dated amendment in `frontend_design.md` §5.

**The tree is clean, committed through `925312d`.** Four commits closed out
that work: `cddfeb3` for Layer C sittings C5-C8, `9fdf55f` for frontend slice
3, `555be6d` for the write-ups, and `925312d` for slice 3's rework against the reference apps. 337 tests passing on a clean tree.

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
- **The dark ground is `#1A1A1A` and its four greys were *solved*, not
  picked.** `surface`, `raised` and `line` reproduce the relationships the
  palette was designed around (1.094x, 1.264x, 1.378x above the ground) to
  three decimals, and `#1A1A1A` is close to the floor — below about `#171717`
  no lighter grey lands on the 1.095x `surface` relationship at all, so a
  deeper ground means redesigning the ramp, not nudging it. Changing any of
  the four means re-measuring every token against **all three surfaces**, not
  just the ground: `dim` on `raised` shipped at 4.43:1 against a 4.5:1 floor
  for weeks because the original pass only ever compared against the ground.
  `accent-ink`, the brand panel's two dark stops and the favicon tile all
  hard-code the ground and have to move with it.
- **Three faces, and the serif is for what the model writes.** Hanken Grotesk
  for all interface text, Source Serif 4 for model replies and hero headlines,
  IBM Plex Mono for token counts, model names, ids and strategy labels. The
  reader's own messages stay in the sans — the serif/sans split is what
  separates what was written for you from what you wrote, so do not "tidy" the
  user bubble into the serif. These are stand-ins for Claude's own Copernicus
  and Styrene, which are licensed and cannot be bundled; if they are ever
  licensed, only the two `--font-*` variables in `index.css` change.
- **The app has one gradient language: directional and warm.** `.brand-panel`
  and `.hero-wash` are both sweeps, and `.hero-wash` carries every entry
  surface — the landing hero, `/app`, and an empty conversation. A centred
  radial bloom was built for the empty conversation and deleted the same day:
  it did not fit beside two directional gradients, and no amount of tuning was
  going to change that. Also worth keeping from it: **a two-stop radial bands
  on a dark ground**, and where two of them cross the banding shows as a
  mottled corner, so any radial here needs an eased four-stop falloff and a
  single centre. And **a colour alone over near-black is paint, not light** —
  9% moss over `#1A1A1A` lands on `#272B24`, army green; light desaturates
  toward the ink at its core.
- **`dim` may not sit on a gradient — not the brand panel, not `.hero-wash`.**
  It measures 4.20:1 on the panel's lightest stop and 3.67:1 / 3.93:1 on the
  wash's strongest, against a 4.5:1 floor. Use `muted` or stronger on either
  surface. This is why the landing hero's stats row and the app's start surface
  read `muted` where the rest of the app reads `dim`, and it is not an
  inconsistency to tidy up. `muted` itself only clears the wash by 0.12 and
  0.20 in the two themes, so raising `--wash-sweep` or `--wash-glow` means
  re-measuring every token on that surface, not eyeballing it.

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

**Slice 5's navigator has a home now: a right-hand panel behind a switch,
holding the tree and the graph over one selection state, its open state
remembered per user and an overlay below `lg`** (§8.18). The left sidebar is
the conversation list and stays that way.

**Frontend slice 4 — span branching — is next, and is the alternative
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

- **2026-09-08**: **Slice 3 reworked against Claude, ChatGPT and Gemini as
  references.** No backend change; 337 still passing. Full detail in
  `docs/PROGRESS.md`, durable rules already promoted into **Standing gotchas**.
  **The dark ground deepened to `#1A1A1A` — a LOCKED change**, superseded in
  writing in `frontend_design.md` §5. The four greys were *solved* to preserve
  the palette's designed relationships to three decimals, and it **repaired a
  live failure**: `dim` on `raised` was shipping at 4.43:1 against a 4.5:1
  floor, missed because the original pass only measured against the ground.
  **`.hero-wash` rebuilt** (0.09 alpha measured as designed and read as
  nothing) and now carries all three entry surfaces. A bespoke centred glow was
  built for the empty conversation and **deleted the same day** — it was a
  second gradient language beside two directional ones.
  **The chat page was stripped**: header band, role labels, the composer's
  raised band, the `Enter sends` hint everywhere but the empty state. The
  conversation's facts moved to one line under the prompt and **the id is
  gone**.
  **`/app`'s title form is gone** — it is the same `StartPane` as an empty
  conversation, nothing is created until something is sent, and titles are
  derived from the first message in the create call.
  **The sidebar collapses and persists**; rows went two lines to one.
  **A strategy switch in the prompt box**, driving the `PATCH` route that has
  existed since the conversation layer — *not* slice 6's picker.
  **`MenuSelect` replaced a native `select`**, because a `select`'s dropdown is
  drawn by the OS and cannot be themed. Only shadow in the app.
  **Fonts: Hanken Grotesk + Source Serif 4 + IBM Plex Mono.** Claude's own
  Copernicus and Styrene are licensed and cannot be bundled. The serif is now
  used for body copy — model replies only — reversing §4's old rule.
  **Next: frontend slice 4 — span branching**, unblocked since the message
  layer.
