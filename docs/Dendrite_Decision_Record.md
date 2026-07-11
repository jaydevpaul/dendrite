---
type: project-decision-record
project: Dendrite
status: Phase 2 — data layer fully locked; ready for implementation
updated: 2026-07-05
---

# Dendrite — Complete Decision Record

Single source of truth for Dendrite. Covers the thesis, scope, evaluation plan,
data model, and the full database schema. Written to be read top-to-bottom by
a new contributor (or a fresh AI session) with no prior context.

Rule: **re-read before changing scope.** Reopening a locked decision requires a
new record that supersedes the relevant section, not a casual pivot.

---

## 1. Thesis

Existing branching AI chat tools treat conversational context as either fully
inherited or fully isolated — a binary that wastes tokens or loses information.
Dendrite introduces **structured, graph-aware context composition**. When a user
branches from a highlighted span within a parent response, the child branch
receives a hierarchically composed context: the span at full fidelity, the
parent at medium fidelity, and older ancestors at decaying fidelity. Beyond a
depth threshold, ancestors are compressed into summaries with retrieval
drill-down — a two-tier memory system where summaries are the default and full
text is retrieved on demand when relevance justifies the cost. Evaluated against
linear-context and full-inheritance baselines using an LLM-judge framework,
measuring **answer quality per token**.

Load-bearing terms:

- **Graph-aware context composition** — context is built by walking the
  conversation graph, not concatenating linear history.
- **Hierarchical fidelity decay** — content closer to the branch point is
  higher fidelity; distant content decays toward summary.
- **Two-tier memory** — summaries by default beyond a depth threshold; full text
  retrieved on demand.
- **Retrieval drill-down** — a relevance-scoring step decides when to swap a
  summary back to the original text.
- **Quality per token** — the evaluation metric. The ratio, not raw quality or
  raw cost.

---

## 2. Differentiator

Three legs; if any is missing the differentiation collapses. Protect all three
through MVP.

1. **Span-level branching** — the feature. Unfilled in the competitive
   landscape (see section 3).
2. **Hierarchical context composition with retrieval drill-down** — the
   technical substance under the feature.
3. **Published evaluation results** — the rigor that turns it from a hack into a
   portfolio piece.

---

## 3. Competitive Landscape

| Tool | Model | Gap vs Dendrite |
|---|---|---|
| **gitchat** | Miro-like canvas; each prompt/response is a node joined by arrows | Mostly a UI project. No familiar chat interface. No span selection. No context management. |
| **Prompt-Tree** | Message-as-node DAG; 3-layer memory (user profile, memory bank, folder doc); multi-model; compression | Strongest player. Branches on multiple-models, not on span selection. No published evaluation. |
| **treeGPT** | Message-pair nodes on a canvas; vim keybindings; model routing | Branch button per node — no span-level branching. Chat window still clutters. No evaluation. |
| **HN-surfaced tools** | Various | Same pattern: branch off a whole response, never a selected span. |

Two industry-wide gaps Dendrite fills: **span-level (sub-response) branching**,
and **published, rigorous evaluation** of the context strategy. Dendrite competes
on being *more principled*, not more featured.

---

## 4. Scope

### In MVP

1. Linear chat with **span-anchored branching**. Select any contiguous span in
   an AI response, create a child branch anchored to it. Anchor survives reload.
   DAG, one parent per node.
2. **Hierarchical context composition**. Anchor span full text + parent full
   text + older ancestors summarized via a swappable decay function.
3. **Two-tier memory** beyond depth N (default 3). Ancestors stored as summaries
   + embeddings; a retrieval step drills down to full text for top-k relevant
   hits.
4. **Pluggable context strategies** (see section 5), selectable per-branch and
   per-eval-run.
5. **Evaluation framework** (see section 7).
6. **Persistence + multi-user auth**. Real DB, users, sessions.
7. **Minimal coherent UI**. Sidebar tree navigation.

### Not in MVP (closed, not open for casual reopening)

Canvas/graph visualization (→ MVP+1, first post-MVP task) · real-time collab
(v2/v3, budget 8–12 wks) · sibling-branch bridging (v2, manual only) ·
multi-model branching · tools/MCP · mobile UI · user-facing "compress chain into
node" · fork-entire-conversation (post-MVP; note that branching already covers
sub-conversation forking — a whole-conversation fork is a separate, deferred
feature).

### The canvas decision

Deferred to MVP+1 (Path C). Rationale: canvas is the most aesthetic but least
novel part; trading it against retrieval drill-down would weaken the thesis.
Recruiters look at current repo state, not history — no penalty for it landing a
week after MVP.

---

## 5. Context Strategies (five)

| # | Strategy | What it sends to the model |
|---|---|---|
| 1 | `FullInheritance` | Entire ancestor chain at full text (naive baseline). |
| 2 | `ParentOnly` | Immediate parent message only. |
| 3 | `SpanOnly` | The anchored span only — no ancestors. **Valid on branches only** (a continuation has no span). |
| 4 | `HierarchicalDecay` | Span full + parent full + older ancestors summarized. The contribution without retrieval. |
| 5 | `HierarchicalDecayWithRetrieval` | Full thesis — decay plus retrieval drill-down. |

Context construction sits behind an interface with these five implementations,
selectable at runtime. This is the architectural concession that makes A/B
evaluation possible without code changes.

**Decay function is swappable.** `HierarchicalDecay` is a family, not one fixed
algorithm — the decay function (the rule setting how fidelity drops per ancestor
level: linear, exponential, custom) lives behind its own interface and can be
swapped without rewriting the strategy.

### Strategy selection (what is actually decided)

Automatic selection is deliberately minimal — this is the *entire* trigger logic,
there is no question-type classifier:

- Branches **default to `SpanOnly`** at creation; the user may override to any of
  the five.
- Continuations do not pick their own strategy — they inherit via walk-up (see
  section 6).
- `Conversation.default_strategy` is the user's choice for the whole
  conversation, set at creation (excludes SpanOnly).

Strategies are otherwise compared **by the eval harness**, not auto-chosen at
runtime.

---

## 6. Data Model — Conceptual (locked)

Six entities. A "chat window" the user sees is a **view** (a path through the
graph computed at render time), not a stored entity.

- **Conversation** — top-level container. Owns user_id, title, default_strategy,
  root_message_id. Branching does *not* create a new Conversation; the whole DAG
  is one Conversation.
- **Message** — the atom. `role` = user | assistant. A user prompt and an AI
  reply are *separate rows*, not a fused turn.
- **Edge** — parent→child relationship as its own table. Anchor fields populated
  → **branch**; null → **continuation**. No discriminator column needed.
- **Generation** — the record of producing one AI message: strategy_used,
  model_used, composed_context, token counts. One per assistant message; many
  per user message (that's what powers eval + regeneration).
- **MessageSummary** — derived summary; FK on this side, so one message → many
  summaries.
- **MessageEmbedding** — derived vector; FK on this side, so one message → many
  embeddings.

Key rules (locked):

- **Message-as-node, not turn-as-node** — so the eval harness can reuse one user
  message across five strategies; streaming lifecycle; anchors point into AI
  text; regeneration is a new row.
- **Anchors store offsets AND text.** Offsets = fast render path + disambiguate
  repeated text. Text = repair mechanism: if the parent is edited, fuzzy-match
  the stored text to relocate the anchor; if not found, the edge is *orphaned*
  and flagged, not silently reattached.
- **Anchor repair is only for edits.** Regeneration makes a new sibling message
  (old content untouched); summarization writes a derived row (canonical
  untouched). Only edits mutate canonical content.
- **Regeneration never deletes.** A new Generation + new assistant Message; the
  old message stays so branches anchored into it keep working. Storage grows —
  accepted; storage is cheap, user trust is not.
- **Summaries/embeddings are separate tables** carrying `model_used` +
  `created_at`, so model swaps need no migration.

### Strategy lives in three places

| Field | On | Meaning |
|---|---|---|
| `default_strategy` | Conversation | User's choice for the whole conversation. Excludes SpanOnly. |
| `strategy_override` | Edge | Set only when a branch overrides the default. Null on continuations and on branches that accept the default. |
| `strategy_used` | Generation | Historical record of what actually ran. |

Intent (`default_strategy` + `strategy_override`) and history (`strategy_used`)
are not expected to stay in sync — different jobs.

**Strategy resolution — walk up until you find an override.** For any message,
take its parent Edge; if `strategy_override` is non-null, use it; else walk to
the parent of that edge's parent message and repeat. Reach the root with no hit →
fall back to `Conversation.default_strategy`. Most-specific override wins; nested
branches govern their own subtree.

---

## 7. Evaluation Framework (part of MVP, not a stretch goal)

- **Task set:** 20–30 curated multi-turn scenarios that exercise sub-response
  branching. Synthetic + adapted-from-public acceptable.
- **Quality signal:** LLM-as-judge, 1–5, with a documented rubric. Chosen over
  human rating (doesn't scale), embedding similarity (measures similarity not
  correctness), task-specific metrics (don't generalize). Rubric design is where
  rigor shows.
- **Baselines:** the five strategies in section 5.
- **Metrics:** answer quality (judge score), total tokens (in+out), **quality
  per token** (headline).
- **Deliverable:** a markdown report in the repo, linked from README, including
  negative results if any strategy fails to beat baselines.

Note: failed Generations have null token counts — the harness must filter them
out when summing tokens, or quality-per-token math is polluted.

---

## 8. Architecture Decisions

### 8.1 Database — Postgres + pgvector (single system)

One database, not Postgres + a separate vector store (Pinecone/Qdrant/Weaviate).

Rationale: MVP scale is low thousands of embeddings — pgvector handles it with
room to spare. A second stateful system doubles the backup/monitoring/outage
story and opens a consistency gap (Postgres write succeeds, vector write fails →
silent retrieval degradation). For a solo dev at 8–10 hrs/week the operational
tax outweighs any performance the second system would buy. "Postgres + pgvector,
trade-off explained" is also a stronger senior signal than reaching for a
brand-name vector DB.

Insurance: the embedding call site sits behind a thin `EmbeddingStore`
interface (`index`, `query`, `delete`). One implementation for MVP; swapping is
possible later without touching call sites.

Migration trigger (name it, don't hand-wave "if we get big"): revisit only when
embedding count reaches the hundreds of thousands *and* retrieval p95 latency
under real concurrency exceeds the 1–2s composition budget.

### 8.2 Embedding isolation — one table, isolation by query

All embeddings live in **one `MessageEmbedding` table**. Conversations/users are
*not* separated into per-conversation tables or per-user databases (both are
known anti-patterns: migration pain, catalog/autovacuum overhead, tiny useless
indexes). Isolation is a *logical* property enforced in the query: every
retrieval filters by ancestor set (recursive CTE) + `model_used`, and implicitly
by conversation/user via the foreign keys.

Because isolation is logical, guard the failure modes:

- **Forgotten WHERE = cross-tenant leak.** Every data-access function takes
  `user_id` as a required param; authorization lives in one layer. Optional
  belt-and-suspenders: Postgres Row-Level Security.
- **Embedding-model drift.** Embeddings from different models live in different
  vector spaces and aren't comparable. The `model_used` filter protects every
  retrieval query — never omit it.

### 8.3 IDs — UUID v7 everywhere

UUID v7 for all primary keys. Reasons: unguessable (no count leakage in URLs,
matters for a multi-user, URL-addressable product), app-side generation lets you
build a whole related-row graph in memory before insert (see branch-creation
scenario), eval fixtures are easier to construct deterministically. UUID v7
specifically embeds a timestamp so rows sort in creation order — this removes the
classic random-UUID(v4) index-insert penalty.

Caveat to state correctly: **UUID is defense-in-depth, not access control.** Real
isolation is the `user_id` filter on every query; unguessable IDs just raise the
cost of exploiting a bug in that filter.

### 8.4 Ancestor-walk indexing — recursive CTE for MVP

Both hot walks are cheap: context composition walks a *bounded* depth (~3);
strategy resolution *early-terminates* at the first override. A recursive CTE
with a B-tree on `edge.child_message_id` does each level in one index lookup.

Do **not** add path enumeration or a closure table pre-emptively — they don't
help bounded/early-terminating walks and add write cost + a re-parenting
correctness risk. Escalation path only if measured slow: (1) recursive CTE →
(2) denormalized `depth_from_root` column → (3) path enumeration (likely only
when the MVP+1 canvas needs whole-tree reads) → (4) materialized ancestor table.
Skip stages you don't need.

**Edge topology is immutable (LOCKED).** Anchor repair changes
`anchor_start`/`anchor_end`/`anchored_text` only. An Edge's `parent_message_id`
and `child_message_id` are set once at creation and never change — there is no
re-parenting in MVP. Every ancestor-walk query (context composition and strategy
resolution) relies on this: the tree shape walked yesterday is the same today, so
cached paths, any future `depth_from_root`, and any future closure table stay
valid. A "move branch to a new parent" feature would break this assumption and
requires its own superseding decision record.

### 8.5 Summarization — async, lightweight

Summaries generated **asynchronously in the background** after a message is
created (not eager — most messages never reach depth N; not lazy on request —
adds latency). MVP infra: FastAPI BackgroundTasks or **arq** (asyncio queue on
Redis). Not Celery — its priorities/routing/multi-broker features solve problems
Dendrite doesn't have. Upgrade path to Celery stays open.

### 8.6 Context-composition latency — 1–2s budget, graceful degradation

Target for the whole compose step before the LLM starts streaming: 1–2s
end-to-end. Failure modes get deliberate fallbacks, never silent failure:

- Embedding service down → fall back to `HierarchicalDecay` (no drill-down).
- Summary not yet generated → use full text for that ancestor (costlier, still
  correct).
- Chain unusually deep → cap the walk, accept truncation.

---

## 9. Database Schema (field-level, locked)

Global rules:

- **`text` everywhere** — in Postgres `text` and `varchar` have identical
  performance; `varchar(n)` only adds a length cap. Enforce any length limits in
  app code, not the column type.
- All timestamps **`timestamptz`**, `default now()`.
- Strategy fields are **`text` + CHECK**, not native enums — the strategy set
  already grew once (4 → 5); native Postgres enums are a one-way door
  (rename/remove is painful). CHECK constraints are trivial to alter.

### Conversation
| Column | Type | Notes |
|---|---|---|
| id | uuid | PK (v7) |
| user_id | uuid | FK → User, NOT NULL |
| title | text | NOT NULL, default `'Untitled'` (auto-title overwrites it) |
| default_strategy | text | NOT NULL, CHECK in the 4 non-SpanOnly strategies |
| root_message_id | uuid | FK → Message, NULLABLE (set after first message) |
| created_at | timestamptz | NOT NULL, default now() |
| updated_at | timestamptz | NOT NULL, default now() |

### Message
| Column | Type | Notes |
|---|---|---|
| id | uuid | PK (v7) |
| conversation_id | uuid | FK → Conversation, NOT NULL |
| role | text | NOT NULL, CHECK (role IN ('user','assistant')) |
| content | text | NOT NULL, empty string allowed (streaming starts blank) |
| created_at | timestamptz | NOT NULL, default now() |
| updated_at | timestamptz | NOT NULL, default now() (moves only on edit) |

### Edge
| Column | Type | Notes |
|---|---|---|
| id | uuid | PK (v7) |
| parent_message_id | uuid | FK → Message, NOT NULL |
| child_message_id | uuid | FK → Message, NOT NULL, **UNIQUE** (one parent max) |
| anchor_start | integer | NULLABLE |
| anchor_end | integer | NULLABLE |
| anchored_text | text | NULLABLE |
| strategy_override | text | NULLABLE, CHECK in the 5 strategies |
| created_at | timestamptz | NOT NULL, default now() |

Constraints:
```sql
CHECK (num_nonnulls(anchor_start, anchor_end, anchored_text) IN (0, 3)) -- all-or-nothing
CHECK (anchor_start IS NULL OR anchor_start >= 0)                       -- non-negative
CHECK (anchor_start IS NULL OR anchor_end > anchor_start)               -- valid span
CHECK (anchored_text IS NULL OR anchored_text <> '')                    -- no empty anchor text
CHECK (strategy_override <> 'SpanOnly' OR anchor_start IS NOT NULL)     -- SpanOnly needs a span
```

### Generation
| Column | Type | Notes |
|---|---|---|
| id | uuid | PK (v7) |
| user_message_id | uuid | FK → Message, NOT NULL |
| assistant_message_id | uuid | FK → Message, NOT NULL, **UNIQUE** (one generation per assistant msg) |
| strategy_used | text | NOT NULL, CHECK in the 5 strategies |
| model_used | text | NOT NULL |
| composed_context | text | NOT NULL (exact context sent to the LLM — reproducibility) |
| input_tokens | integer | NULLABLE (null if generation failed pre-count) |
| output_tokens | integer | NULLABLE |
| created_at | timestamptz | NOT NULL, default now() |

### MessageSummary
| Column | Type | Notes |
|---|---|---|
| id | uuid | PK (v7) |
| message_id | uuid | FK → Message, NOT NULL |
| summary_text | text | NOT NULL |
| model_used | text | NOT NULL |
| created_at | timestamptz | NOT NULL, default now() |

No unique constraint — many summaries per message allowed. Selection logic
("most recent for the active model") lives in code.

### MessageEmbedding
| Column | Type | Notes |
|---|---|---|
| id | uuid | PK (v7) |
| message_id | uuid | FK → Message, NOT NULL |
| embedding | vector(1536) | NOT NULL (MVP model: `text-embedding-3-small`) |
| model_used | text | NOT NULL (filter on this in every retrieval) |
| created_at | timestamptz | NOT NULL, default now() |

### Indexes (LOCKED starting set)

Vector index:
```sql
CREATE INDEX ON message_embedding USING hnsw (embedding vector_cosine_ops);
```

B-tree indexes (all single-column, on FKs filtered/joined by):
- `edge.child_message_id` — ancestor walk steps up via "edge whose child is me."
  (Already created by the UNIQUE constraint; listed for clarity.)
- `edge.parent_message_id` — "children of this message" (tree render, branch
  indicators).
- `message.conversation_id` — "all messages in this conversation" (loads every
  conversation open).
- `message_summary.message_id` — summary lookup during context composition.
- `message_embedding.message_id` — join key back to Message during retrieval
  (separate column from the HNSW index, which is on `embedding`).
- `generation.user_message_id` — "all generations for this user message" (eval +
  regeneration history).

No composite or partial indexes yet — those are added only after a measured slow
query, not speculatively.

---
# Dendrite — Entity-Relationship Diagram

Companion to section 9 of the decision record. This is the at-a-glance view;
section 9's tables remain authoritative (the diagram cannot show CHECK
constraints — the five on Edge and the strategy-value checks).

```mermaid
erDiagram
  USER ||--o{ CONVERSATION : owns
  CONVERSATION ||--o{ MESSAGE : contains
  MESSAGE ||--o{ EDGE : "parent of"
  MESSAGE ||--o| EDGE : "child of"
  MESSAGE ||--o{ GENERATION : "prompted (if user)"
  MESSAGE ||--o| GENERATION : "produced (if assistant)"
  MESSAGE ||--o{ MESSAGE_SUMMARY : has
  MESSAGE ||--o{ MESSAGE_EMBEDDING : has
  USER {
    uuid id PK
  }
  CONVERSATION {
    uuid id PK
    uuid user_id FK
    text title
    text default_strategy
    uuid root_message_id FK
    timestamptz created_at
    timestamptz updated_at
  }
  MESSAGE {
    uuid id PK
    uuid conversation_id FK
    text role "user or assistant"
    text content
    timestamptz created_at
    timestamptz updated_at
  }
  EDGE {
    uuid id PK
    uuid parent_message_id FK
    uuid child_message_id FK "UNIQUE (one parent max)"
    integer anchor_start "null if continuation"
    integer anchor_end "null if continuation"
    text anchored_text "null if continuation"
    text strategy_override "null means use default"
    timestamptz created_at
  }
  GENERATION {
    uuid id PK
    uuid user_message_id FK
    uuid assistant_message_id FK "UNIQUE (one gen per assistant msg)"
    text strategy_used
    text model_used
    text composed_context
    integer input_tokens "nullable"
    integer output_tokens "nullable"
    timestamptz created_at
  }
  MESSAGE_SUMMARY {
    uuid id PK
    uuid message_id FK
    text summary_text
    text model_used
    timestamptz created_at
  }
  MESSAGE_EMBEDDING {
    uuid id PK
    uuid message_id FK
    vector embedding "1536 dims"
    text model_used
    timestamptz created_at
  }
```

## 10. Validation Scenarios

1. **Continuation** — 1 user Message, 1 continuation Edge, 1 assistant Message,
   1 continuation Edge, 1 Generation. All anchor fields null. Strategy resolved
   by walk-up.
2. **Branch creation** — 1 user Message, 1 **branch** Edge (anchors populated,
   `anchored_text` = substring of parent, `strategy_override` = SpanOnly by
   default), 1 assistant Message, 1 continuation Edge, 1 Generation. Note: span
   text lives in `Edge.anchored_text`, not `Message.content`.
3. **Eval, 5 strategies on one user message** — 0 new user Messages (reused), 5
   assistant Messages, 5 Generations (same `user_message_id`), 5 continuation
   Edges. Input fixed, output multiplies — the reason Generation is separate.
4. **Regeneration with existing branches** — old assistant Message stays,
   content unchanged; new assistant Message + continuation Edge + Generation.
   Branches anchored into the old message keep working.

---

## 11. Glossary

- **pgvector** — Postgres extension adding a `vector` column type and
  vector-similarity search. Lets embeddings live in the same DB as everything
  else.
- **`vector(N)`** — column holding an embedding of exactly N numbers. N is fixed
  by the embedding model (`text-embedding-3-small` → 1536). Changing to a model
  with a different N is a schema change.
- **Embedding** — a fixed-length list of numbers representing text meaning.
  Similar text → nearby vectors.
- **HNSW (Hierarchical Navigable Small World)** — an approximate
  nearest-neighbour index for "find the K most similar vectors" fast. Built once
  across the whole table and maintained incrementally on insert; not rebuilt per
  query. Layered graph: sparse top layers give big jumps into the right region,
  dense bottom layer does fine search (like zooming a map country→city→street).
  Approximate — occasionally misses the true top-K, which is fine for relevance
  scoring. Knobs: `m`, `ef_construction`, `ef_search` — leave at defaults until
  measured. Alternative index IVFFlat builds faster/uses less memory but has
  worse recall/speed; HNSW is the right MVP default.
- **How HNSW is actually used at query time** — the planner chooses per query:
  either walk the HNSW index then filter to the ancestor set, or filter to the
  small ancestor set first then brute-force compare. At MVP scale the ancestor
  filter is so selective the planner often picks brute force and HNSW may not
  fire — that's fine; the index costs little and starts paying off for free once
  chains grow. Your job: create the index and write a clear
  filter-then-order-by-distance-limit-K query; Postgres decides the rest.
- **Distance metric** — how vector similarity is scored. **Cosine** for
  Dendrite (OpenAI embeddings are normalized; operator class `vector_cosine_ops`).
  Alternatives: L2, inner product.
- **Decay function** — the rule controlling how much fidelity each ancestor keeps
  as you move away from the branch point (linear, exponential, custom). Swappable
  behind an interface; `HierarchicalDecay` is a family of behaviours, not one.
- **Recursive CTE** — a SQL query that references itself, used here to walk up
  the Edge chain from a message to its ancestors.
- **Closure table / path enumeration** — precomputed ancestor structures.
  Deliberately *not* used in MVP (see section 8.4).
- **UUID v7** — 128-bit unique ID with a timestamp prefix, so IDs sort by
  creation time (index-friendly) while staying unguessable.
- **bigserial** — auto-incrementing integer ID. Rejected: guessable, leaks
  counts, no app-side pre-generation.
- **Row-Level Security (RLS)** — Postgres feature letting the DB itself restrict
  which rows a connection sees. Optional belt-and-suspenders for tenant
  isolation.
- **arq** — lightweight asyncio background-job queue on Redis. MVP choice for
  async summarization over the heavier Celery.

---

## 12. Open Items (next sessions)

Each is pinned to either a milestone or a trigger condition — none is floating.

- **"Current summary" selection rule** in code (when a message has several
  summaries) — *trigger: when selection actually matters, likely Weeks 7–14.*
- **Full failure-mode list** for each context-composition step + its fallback —
  *trigger: near the strategy-interface implementation, Weeks 7–14.*
- **Auth approach** (roll-your-own vs Clerk/Supabase/Auth0) — affects `user_id`.
  *Milestone: backend block, Weeks 3–6.*
- **LLM provider abstraction** (single vs abstracted from day one) —
  *Milestone: backend block, Weeks 3–6.*
- **Deployment target** (affects streaming: SSE vs websocket, cold-start
  tolerance) — *Milestone: backend block, Weeks 3–6.*

Condition-based deferral ("solve when X becomes true") is deliberate here — it's
more honest than forcing a calendar date onto a question you don't yet know
enough to answer.

---

## 13. Anti-Patterns (guardrails)

Scope creep via "wouldn't it be cool" → capture in ROADMAP.md, don't build ·
re-litigating closed decisions → write a superseding record instead · UI before
backend rigor · skipping evaluation because "it feels right" · adding features
just because Prompt-Tree has them · under-budgeting real-time collab (8–12 wks
when it comes).

Scope-expansion impulses peak exactly when you can least afford them (excited
week 3, bored week 10, almost-done week 16). Trust the locked scope.
