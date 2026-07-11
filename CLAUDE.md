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
