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

## Current state (2026-08-30)

**Built:** models + Alembic migrations · `/health` · full auth
(`/auth/signup|login|logout|me`, argon2 + HS256 JWT in an HttpOnly cookie) ·
45 backend tests · frontend slice 1 (landing, signup/login, route guards,
theme toggle) verified end to end through the Vite proxy.

**Not built:** conversation/message routes, generation, summarization,
embeddings, eval framework, the graph navigator.

**⚠ Nothing is committed yet** — auth, tests and all of `frontend/`.

### Running it

```
docker compose up -d                          # Docker Desktop must be running
uvicorn app.main:app --reload --port 8000     # repo root, .venv active
cd frontend && npm run dev                    # :5173
pytest                                        # repo root, 45 passing
```

**The DB is on host port 5433, not 5432.** A native Windows Postgres service
keeps reclaiming 5432 and it *also* has a `dendrite` role and database, so a
wrong port connects successfully into an empty schema instead of failing —
Alembic's "target database is not up to date" was the only symptom. `.env`
exists locally (gitignored) and **overrides code defaults**, so a stale port
there silently re-breaks the connection.

### Standing gotchas

- **Always review Alembic autogenerate output.** It has needed hand-correction
  3 times out of 3: missing `pgvector` import, no `CREATE EXTENSION vector`,
  the `use_alter` circular FK silently dropped, and unnamed constraints that
  make `downgrade()` unrunnable. `metadata.create_all` handles the circular FK;
  Alembic does not.
- **Never add CORS middleware, never weaken the cookie to `SameSite=None`.**
  The Vite proxy (`/auth`, `/health` → :8000) makes both unnecessary. See
  `frontend_design.md` §3 — the half-configured-CORS failure mode is silent.
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
**Backend: conversation + message routes.** This is where `CurrentUser` starts
scoping every query (the authorization discipline in `auth_design.md` §4.3 —
every query filtered by `user.id`, or it is an IDOR) and where the §8.4
recursive-CTE ancestor walk gets built. Frontend slice 2 (conversation list) is
blocked until these exist.

## Progress log

Full history is in **`docs/PROGRESS.md`** — this section carries only the most
recent entry. At the end of each session, append there and replace the entry
below. If a fact will still matter in three months (a port, a run command, a
standing gotcha, a working rule), promote it into **Current state** above
instead of leaving it buried in a dated entry.

- **2026-08-30 (session close)**: Frontend slice 1 complete and verified.
  - `frontend/` builds clean, route-level chunks split, backend's 45 tests
    still pass. Auth verified end to end through the Vite proxy on :5173 —
    401 → 201 signup w/ `Set-Cookie` → 200 `/auth/me` → 409 dup → 401 bad
    password → 422 short password → 204 logout → 401.
  - Palette **LOCKED** (`frontend_design.md` §5): ground `#232323`, ink
    `#EDE6D6`, accent `#9BC47A`. Logo is a leaf whose veins branch.
  - Two superseding entries written to the decision record, both user-approved:
    **§8.10** (UI scope widened; frontend built in parallel with the backend)
    and **§8.9 revised** (graph gated on its own backend prerequisite, not a
    fixed slice order; `MiniGraph` and friends are static specimens, *not* the
    graph slice — do not mistake them for progress).
  - Docs restructured: this log was split out to `docs/PROGRESS.md`. `CLAUDE.md`
    is auto-loaded every session and had grown to ~6,950 tokens, ~6,460 of it
    log; it now carries rules, durable state, and the latest entry only.
  - **Next: backend conversation + message routes.** See *Next task* above.
