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

## Current task
Set up the Python project (dependencies, folder structure), then write the
SQLAlchemy models transcribing section 9 of the decision record. Nothing beyond
the models this session — no auth, no routes, no business logic yet.

## Progress log
Update this at the END of each session: what was built, what's next, any
decision made. This is what a future session reads to pick up cleanly.

- **2026-07-11**: Project scaffolded (`pyproject.toml`, `app/core/` for
  config+async db engine+uuid7 helper, `app/models/` for the six entities).
  All models transcribed field-for-field from decision record section 9,
  verified by compiling actual `CREATE TABLE`/`CREATE INDEX` DDL against the
  Postgres dialect (no live DB needed) — every CHECK constraint, FK, and
  index matches. Two decisions made to fill gaps section 9 left open:
  - Added a minimal stub `User` model (id + created_at only) since
    `Conversation.user_id` needs a real FK target but `User` isn't one of
    the six entities and auth is deferred (section 12). Expand/replace when
    auth lands.
  - DB access is async (SQLAlchemy 2.0 async ORM + asyncpg), matching the
    async-first stack (FastAPI, arq) — not explicitly locked in the record,
    flagged and confirmed with the user.
  - Technical note, not a decision: `Conversation.root_message_id` ↔
    `Message.conversation_id` form a circular FK. Resolved with
    `use_alter=True` on the `root_message_id` FK (SQLAlchemy emits it as a
    separate `ALTER TABLE` after both tables exist) — no schema change, just
    how it's created.
  - Next: nothing beyond models this session per scope. Future sessions:
    Alembic/migration setup, auth (section 12), then routes/business logic.

- **2026-07-12**: No new files; one edit to `app/core/db.py` (by
  user/linter, not this session's own work, but carried forward here since
  it changes generated DDL): `Base` now sets
  `type_annotation_map = {str: Text}`, so every `Mapped[str]` column (e.g.
  `Edge.anchored_text`, `Edge.strategy_override`) compiles to Postgres
  `TEXT` instead of the previous default `VARCHAR`. Verified by recompiling
  `CreateTable(Edge.__table__)` against the Postgres dialect in a scratch
  venv — output confirmed, venv discarded after. This actually brings the
  models closer to the decision record's global rule ("`text` everywhere,"
  section 9) that the original models weren't fully honoring.
  - Also answered questions (no code changes): confirmed no `.venv` is
    committed (excluded via `.gitignore`), confirmed `git init` has not
    been run yet.
  - Next: same as prior entry — Alembic/migration setup, auth (section 12),
    then routes/business logic. Git repo still needs to be initialized
    when the user is ready.

- **2026-07-23**: Stood up the local DB and Alembic; first migration applied.
  - **Local dev DB is now Docker**, not the native install. Native PG18 (EDB
    installer) doesn't ship pgvector and the machine had no C++ build tools,
    so instead of compiling we run `pgvector/pgvector:pg18` as container
    `dendrite-pg` (port 5432, named volume `dendrite_pgdata`). Native PG
    service stopped + set to Manual to free 5432 (reversible). Container env
    vars auto-create the `dendrite` role + DB, matching the app's default
    config — so no `.env` was needed (none committed; running on defaults).
    **Future sessions: `docker start dendrite-pg` before doing DB work.**
  - Added `alembic` dependency; `alembic init -t async alembic` (async
    template because our only driver is asyncpg). Wired `alembic/env.py`:
    `config.set_main_option("sqlalchemy.url", settings.database_url)`,
    `target_metadata = Base.metadata`, and `import app.models` so all seven
    tables register for autogenerate.
  - Autogenerated + hand-corrected the first migration
    `alembic/versions/4624be06dde7_initial_schema.py`. Three autogen gaps
    fixed:
    1. missing `import pgvector.sqlalchemy.vector` (would `NameError`);
    2. no `CREATE EXTENSION vector` — added as first stmt of `upgrade()`
       (dropped in `downgrade()`), else the `vector(1536)` column fails;
    3. **circular FK was silently dropped** — `use_alter=True` excludes the
       `conversation.root_message_id → message.id` FK from `CREATE TABLE`,
       and Alembic (unlike `metadata.create_all`) has no automatic
       post-create ALTER, so the FK would never be created. Replaced the
       inline `use_alter` FK with an explicit `op.create_foreign_key` after
       `message` exists (+ `drop_constraint` first in `downgrade`).
  - Reviewed with `alembic upgrade head --sql` (dry run) before applying,
    then `alembic upgrade head`. Live DB verified: 8 tables (7 + 
    `alembic_version`), pgvector 0.8.5, circular FK present, HNSW index
    `USING hnsw (embedding vector_cosine_ops)`, revision `4624be06dde7`.
  - Next: auth (section 12) to replace the `User` stub, then routes/business
    logic.

- **2026-07-27**: FastAPI app skeleton — first bit of the API layer, no
  business logic. Flagged first that the log's "auth next" is blocked: auth
  approach is an *undecided* open item (section 12), so it can't be coded
  without a decision. Built the decision-free plumbing instead:
  - `app/core/db.py`: added `get_session`, an async `AsyncSession`-per-request
    FastAPI dependency over the existing `async_session_factory`.
  - `app/api/routes/health.py` (new `app/api/` + `app/api/routes/` packages):
    `GET /health` (liveness) and `GET /health/db` (readiness; runs `SELECT 1`
    through `get_session`).
  - `app/main.py`: added a `lifespan` that disposes the engine pool on
    shutdown; mounted the health router.
  - Verified against live `dendrite-pg` (venv Python, direct handler calls —
    `TestClient` unusable, see below): `/health` → `{status: ok}`,
    `/health/db` → `{status: ok, database: reachable}`.
  - Note for future test work: `httpx` is NOT installed, so FastAPI
    `TestClient` fails to import. When real route tests land, add `httpx` +
    `pytest`/`pytest-asyncio` as dev deps (left out here — scope was skeleton
    only).
  - Next: the auth-approach decision (roll-your-own vs Clerk/Supabase/Auth0),
    ideally taken together with the other two Weeks 3–6 open items — LLM
    provider abstraction and deployment target — then real routes.
