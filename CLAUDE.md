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

## Current state (2026-09-09)

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
(`app/api/sse.py`), and `MessageOut.pending`** · **the one real OpenAI client
(`app/llm/openai_client.py`), verified against the live API** · **conversation
delete (`DELETE /conversations/{id}`, the cascade migration
`b1c4d9e77a30`)** · 354 backend tests ·
frontend slices 1, 2 and 3
(landing, signup/login, route guards, theme toggle) · **frontend slice 3 —
linear chat: the persistent conversation sidebar, the thread, the composer, SSE
streaming via `fetch` + `ReadableStream`, retry on an unanswered or unfinished
reply, `StartPane` for an empty conversation, and a title derived from the
first message (`frontend/src/features/messages/`,
`components/conversation-sidebar.tsx`, the rewritten `app-shell.tsx`,
`routes/new-conversation.tsx` and `routes/conversation.tsx`)** — all verified
end to end through the Vite proxy · **frontend slice 4 — span branching: the
selection-to-offsets layer (`selection.ts`, `anchor.ts`), the floating offer
and composer (`span-branch.tsx`), marks with a popover of the branches that
grew from them, and `?from=` re-rooting the thread** · **markdown-rendered
replies with the source-offset mapping that keeps anchors exact
(`reply-markdown.tsx`, `source-spans.ts`, `math.ts`)** · **the sidebar delete
with its confirm dialog (`components/ui/confirm-dialog.tsx`)** ·
**branch delete (`DELETE /conversations/{id}/messages/{message_id}`,
`delete_branch()` and its descendant walk in `app/services/message.py`)** ·
**frontend slice 5 — the branch navigator: a right-hand panel holding a tree
and a graph over one selection, both drawn from the graph the page already has
(`frontend/src/features/navigator/`), its open state remembered per user
(`lib/navigator.ts`), and both side panels resizable against a thread floor
(`lib/panel-size.ts`, `components/ui/resize-handle.tsx`)** · **`plainPreview`
(`features/messages/preview.ts`), used everywhere a reply is quoted rather than
read** · 96 frontend tests in Vitest + jsdom.

**Not built:** summarization (the write side — nothing populates
`message_summary` yet), the embedding write side (nothing populates
`message_embedding` yet either), eval framework, slice 6's strategy picker. **The two write sides are the important gap:**
`HierarchicalDecay` and retrieval both read tables nothing fills, so they
silently degrade to plainer strategies and §7's whole comparison is
unmeasurable until they exist.

**No React component is rendered by any test.** Vitest runs the string and DOM
maths — offsets, the source-span sweep, the thread walk — and there is no
testing library, so anything that only shows up when a component renders is
verified by reading and by using the app.

**Layer C is finished.** All twelve shape decisions are written up as §8.15
(D1–D12); the build decisions are in §8.16 (C1–C2), §8.17 (C6–C8) and §8.19
(C9 as built). Do not re-litigate them. §8.15's D8, D9 and D11 each carry a dated
correction or narrowing — read the parentheticals, not just the headline.

**§8.18 settles two frontend shape questions** that slice 3 forced: which path
the linear view walks (continuation edges only, newest child — the standing
gotcha below says why both halves matter), and that the branch navigator now
lives in a **right-hand panel behind a switch**, because the left sidebar holds
the conversation list. The palette gained one token, `scrim`, recorded as a
dated amendment in `frontend_design.md` §5.

**§8.19 settles three more things** (2026-09-08): that a conversation can be
deleted and that the delete really deletes, cascading in the database rather
than in the service; that **model replies are rendered markdown**, which
supersedes the old "no markdown renderer, and that is load-bearing" rule and
replaces the DOM-equals-storage equality with a verified source-offset
mapping; and the two wire-format facts C9 turned out to need.

Committed through `3273536`. **Uncommitted: all of slice 5 and branch
delete** — `frontend/src/features/navigator/`, `lib/navigator.ts`,
`lib/panel-size.ts`, `components/ui/resize-handle.tsx`,
`features/messages/preview.ts` and its test, `tests/test_branch_delete.py`,
`delete_branch()` in `app/services/message.py`, the DELETE route, and the
changes in `app-shell.tsx`, `conversation.tsx`, `message-turn.tsx`, `api.ts`
and `queries.ts`. **368 backend** (2 skipped, the live LLM pair) and **96
frontend** passing.

**`design/` is untracked and undecided.** A design canvas — `Main.dc.html`,
`Problem.dc.html`, `canvas.json`, and a 2.5MB
`dendrite-context-strategies.html`. Nothing in the app imports it, and whether
it belongs in the repo, in `docs/`, or in `.gitignore` has not been settled.

### Running it

```
docker compose up -d                          # Docker Desktop must be running
uvicorn app.main:app --reload --port 8000     # repo root, .venv active
cd frontend && npm run dev                    # :5173
pytest                                        # repo root, 368 passing
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
- **Deleting a message cannot be left to a cascade, because a message does not
  point at its parent — the edge does.** Cascading from one message takes its
  edges and leaves its children as messages nothing points at, and *a message
  nothing points at is how the root of a conversation is identified*. The
  result is a conversation with several roots and a thread that walks whichever
  one it finds first. `delete_branch()` therefore collects the whole subtree
  itself and deletes the messages explicitly.
- **The descendant walk joins on `parent_message_id`, and there that is
  correct** — the exact opposite of the ancestor walk, where joining on that
  column is the bug that fans out and hangs. Going down, the fan-out is the
  point: a message may have several children and all of them are going. Do not
  "fix" either walk into the other. Both filter `conversation_id` inside the
  CTE, in the seed and the recursive step, and both carry a 200-level guard.
- **A reply that is *quoted* rather than read has to go through
  `plainPreview()`.** The stored message is markdown, so a navigator row, a
  graph card, a branch crumb or the span above the branch composer will show
  `**attention layer**` and raw LaTeX where a phrase belongs — the same failure
  as not rendering a reply at all, only in miniature. It is not a parser and it
  is not reversible, so nothing anchored may be computed from its output;
  anchor offsets are always counted against the stored string.
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

- **An `.env` change needs the server killed and restarted.** `Settings()` is
  constructed at import, and `--reload` watches `.py` files only — so flipping
  `DENDRITE_LLM_CLIENT` and resending gets you the fake's reply again with
  nothing on screen saying why. A fresh `python -c` printing the setting proves
  the file, never the running process.
- **Bash heredocs on this machine eat one level of backslash escaping.** A test
  file written with `cat <<'EOF'` came out with real newlines where `\n` was
  meant and `\[` where `\\[` was, which esbuild reported as an unterminated
  string literal three lines away from the cause. Anything containing
  backslashes or escape sequences goes through the editor tools instead.
- **Alembic autogenerate does not compare a foreign key's `ON DELETE` action at
  all** — it reports "no changes" for a migration that changes every one of
  them. That is the fourth thing it gets wrong about this schema, alongside the
  missing `pgvector` import, the absent `CREATE EXTENSION vector`, and the
  silently dropped `use_alter` circular FK.
- **Chat completions report no `usage` unless the request asks for it.**
  `stream_options={"include_usage": True}`, or every `Generation` row lands
  with null token counts and §7 has nothing to divide quality by. The usage
  frame also arrives with an **empty `choices`**, so a loop that reads
  `chunk.choices[0]` unconditionally raises `IndexError` on the last frame of a
  perfectly good stream.
- **The live LLM tests are gated on `DENDRITE_LIVE_LLM=1`, not on the key.**
  Gating on the key would mean that putting one in `.env` silently bills every
  `pytest` run. In PowerShell: `$env:DENDRITE_LIVE_LLM = "1"` on its own line —
  bash's `VAR=x cmd` prefix is a parse error there.
- **The source-offset layer's failure mode is silence.** Nothing throws, the
  reply renders perfectly, and branching quietly stops being offered. Three
  ways it happened: a mark that did not carry the stamp of the run it replaced
  (`MarkedSpan` draws its own element, so it must copy `data-src-start`/`-end`
  across); two selection boundaries with no stamped run around them, which fall
  back in opposite directions, cross, and used to make `offsetsForRange` return
  null; and a branch anchored on a formula, which resolved and therefore
  counted as marked while nothing drew it, leaving the branch reachable from
  nowhere. The load-bearing test is a sweep asserting every measurable run
  contains exactly the source text it claims — not a list of cases.
- **Any rewrite of a reply's text before parsing must preserve its length.**
  `\[` → `$$` is two characters for two, which is the only reason the LaTeX
  swap is allowed to run: the parser's positions have to stay positions in the
  stored string. `math.ts` asserts it and returns the original if it fails.
- **`focus()` scrolls the field into view.** The branch composer opens in the
  middle of a thread, so it needs `focus({ preventScroll: true })` or the reply
  the span was taken from slides off screen at the moment the reader is about
  to write about it.
- **A `<mark>` is inline, so a mark round a block collapses it.** A branch
  anchored on a formula or a whole code block puts the mark round the node, and
  `.reply-prose mark:has(...)` has to make that one `display: block`.

## Companion docs

- `docs/Dendrite_Decision_Record.md` — authoritative spec; wins over everything.
- `docs/auth_design.md` — auth architecture, threat model, flows.
- `docs/frontend_design.md` — frontend stack, **locked palette** (§5), slice order.
- `docs/PROGRESS.md` — full session history. Read on demand.

## Next task
**The summarization and embedding write side.** Layer C is finished, frontend
slice 4 has shipped, and this is now the gap that matters: nothing populates
`message_summary` or `message_embedding`, so `HierarchicalDecay` and
`HierarchicalDecayWithRetrieval` both read tables that are always empty. They
degrade quietly to plainer strategies, which means §7 would compare five arms
where two of them are not doing the thing they exist to test. **The project's
own thesis is unmeasurable until this exists.**

What it needs, from §8.5 and §8.6: summarization is **async and lightweight** —
written after a message lands, not on the read path — and composition must
still work when a summary is missing, which it already does. The embedding side
writes `vector(1536)` from `text-embedding-3-small` and is the same shape of
job: one row per message, written off the request. Both now have a real client
to call, so the only new decisions are *when* the work is queued and what
happens to a message whose summary never lands.

Read §8.5, §8.6 and §9's `message_summary` / `message_embedding` rows before
starting, and note that `load_summaries()` and the retrieval query already
exist and define what the writers have to produce.

The nine Layer C sittings, all done:

| # | Piece | State |
|---|---|---|
| C1 | `LLMClient` protocol, `FakeLLMClient`, LLM config keys | **done** |
| C2 | Context types, strategy interface, `FullInheritance`, `ParentOnly`, `SpanOnly` | **done** |
| C3 | Decay function interface + `TieredDecay` + the summary reader | **done** |
| C4 | `HierarchicalDecay` | **done** |
| C5 | Ancestor-scoped pgvector retrieval + `HierarchicalDecayWithRetrieval` | **done** |
| C6 | `compose_context()` — resolve → walk → dispatch → degradations | **done** |
| C7 | Generation service — §8.14's write pattern, the `Generation` row, the failure path | **done** |
| C8 | SSE route, the four events, `MessageOut.pending` | **done** |
| C9 | The one concrete OpenAI client, against the real API | **done** |

**After the write side:** slice 6's strategy picker, which shows the composed
context and the token cost beside each arm — not the per-branch menu slice 4
already added. Slice 5's navigator has shipped. **The eval is last, and it is
the only piece that costs real money**: ~$2.60 a run against a $20 budget, so
it runs when there is something worth measuring.

## Progress log

Full history is in **`docs/PROGRESS.md`** — this section carries only the most
recent entry. At the end of each session, append there and replace the entry
below. If a fact will still matter in three months (a port, a run command, a
standing gotcha, a working rule), promote it into **Current state** above
instead of leaving it buried in a dated entry.

- **2026-09-09**: **Frontend slice 5 — the branch navigator — and branch
  delete.** 368 backend tests (2 skipped, the live LLM pair) and 96 frontend, up
  from 354 and 68. All of it uncommitted. Written up from the working tree
  rather than a transcript, since the work was done in a separate chat — full
  detail in `docs/PROGRESS.md`, durable rules promoted into **Standing
  gotchas** above.
  **The navigator is `frontend/src/features/navigator/`** — a tree view and a
  graph view over one selection, both drawn from the graph the page already has,
  so switching is a render and refetches nothing. **A turn fuses a question with
  its reply into one node and splits the moment a question has more than one
  reply**, which is regeneration and the eval's fan-out — the cases
  message-as-node exists to represent. Fusion is a rendering choice only; the
  message is still the stored unit and still what an anchor points into.
  **Layout is deterministic and there is no graph library**: every node has one
  parent, so depth sets the row and a sweep sets the lane, and two screenshots
  of the same conversation are identical. Sibling order matches the linear
  walk's newest-first-with-an-id-tiebreak, so the two views cannot disagree.
  **Selecting is separate from going there** — a click selects, the footer, a
  double-click and Enter open the path.
  **Both side panels are now resizable**, and the two preferences are stored
  differently on purpose: **width per browser** (a width is a fact about the
  window it was dragged in), **open state per user** (a habit, and two people
  sharing a browser should not inherit each other's). Every width is clamped
  against the viewport with a 420px thread floor.
  **Branch delete** is `DELETE /conversations/{id}/messages/{message_id}`, and
  only a branch: the root is 422 because that is the conversation's own route,
  a continuation is 422 because it would take the rest of the thread. The
  subtree is collected by a recursive CTE and the messages deleted explicitly —
  the cascade reasoning is now a standing gotcha. The client invalidates rather
  than patches, because working out locally which rows went would re-implement
  the server's walk where it can drift.
  **`plainPreview()`** strips markdown wherever a reply is quoted rather than
  read. Not a parser, and never used for anything anchored.
  **`design/` is untracked and undecided** — a design canvas including a 2.5MB
  HTML file that nothing imports.
  **Next: the summarization and embedding write side**, unchanged and now the
  only thing between here and a measurable thesis.
