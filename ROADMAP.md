# Dendrite — Roadmap

Ideas captured but deliberately **not built**, per the section 13 anti-pattern
("scope creep via *wouldn't it be cool* → capture in ROADMAP.md, don't build").

Nothing here is a commitment. An item leaves this file in one of two ways: it
earns a superseding entry in `docs/Dendrite_Decision_Record.md`, or it is struck
out as rejected with the reason.

---

## Eval hypotheses

Claims that the section 7 harness could actually settle. These belong here
rather than in the code because deciding them by intuition is the section 13
anti-pattern "skipping evaluation because it feels right."

### `AdaptiveBudget` — a sixth strategy (raised 2026-08-30)

**The claim.** If the composed context fits comfortably in the model's window,
send the ancestor chain at full fidelity; only decay once the budget is
threatened. This is what linear chat products (ChatGPT, Claude) effectively do:
full transcript verbatim, with eviction or summarization of the oldest turns
once it stops fitting.

**Why it is not the default.** Three arguments against, none of them fatal:

1. The metric is **quality per token** (section 1), not quality. "There is room,
   so send everything" is precisely the *wastes tokens* half of the binary the
   thesis rejects — it just only spends when it can afford to.
2. Dendrite is not linear. In a branch off a span about topic X, ancestors
   covering Y and Z are distractor context, not free context. The span anchor is
   the user saying *this is what I mean*; backfilling because there is room
   contradicts the gesture. Fitting is not the same as helping.
3. It would blur the eval. An adaptive strategy is `FullInheritance` on short
   conversations and `HierarchicalDecay` on long ones, so a short test
   conversation would measure the former under the latter's name.

**~~Why the premise may not even bind.~~ Corrected 2026-09-02 — this paragraph
read: "Context composition walks the *ancestor path*, not the whole DAG, and
section 8.4 bounds that walk at roughly depth 3. The composed context is already
small, so at MVP scale `AdaptiveBudget` would resolve to `FullInheritance` nearly
every time."** Section 8.13 established that 8.4's `~3` is a *fidelity tier*, not
a bound on the walk — composition climbs to the root, with 200 as a runaway
guard. So the composed context is **not** already small, and this argument
against `AdaptiveBudget` no longer holds. The three arguments above are
unaffected; argument 3 in particular gets stronger, since a deep walk makes the
`FullInheritance`/`HierarchicalDecay` blur depend on conversation length rather
than being fixed.

**Trigger.** After the first full eval run across the five locked strategies. If
the data shows `FullInheritance` winning on quality-per-token at low depth, that
is evidence for a budget-aware strategy, and it earns a superseding record with
numbers behind it.

Until then the create-time default is **`HierarchicalDecayWithRetrieval`**
(`app/models/_shared.py`, `DEFAULT_STRATEGY`) — the full thesis, strategy 5 of
section 5. Chosen over plain `HierarchicalDecay` because it is the thing the
project exists to test, and because it costs nothing to set early: section 8.6
already specifies degrading to `HierarchicalDecay` when the embedding service is
unavailable, which is exactly the state of the world until the embedding
pipeline is built.

---

## Deferred product surface

- **Conversation deletion.** Not built with the conversation routes
  (2026-08-30): frontend slice 2 needs list/create/empty-state only, and the
  cascade semantics deserve their own decision once Message, Edge, Generation,
  MessageSummary and MessageEmbedding rows exist to cascade over. Note the
  tension with the locked "regeneration never deletes" rule — a conversation
  delete is a different promise from a message delete, and the record should say
  so explicitly rather than leave it inferred.
- **Conversation list pagination.** The list route returns every conversation a
  user owns. Fine at portfolio scale; revisit if a test account ever gets past a
  few hundred.

---

## Deferred cost work

- **Prompt caching for the composed prefix** (raised 2026-09-03, section 8.15
  D11). Cached input is ~90% cheaper, and cache reads do not count toward
  rate limits. `FullInheritance` resends the entire ancestor chain on every turn,
  so it is the arm that would benefit most — and section 8.15 D3 chose real
  multi-turn messages partly *because* separate ancestor turns form a
  byte-identical prefix that grows at the end, which is what a cache breakpoint
  needs. Not built: section 13 says measure first, and section 7's first eval run
  is what produces the token numbers that would justify it. **Trigger: if an eval
  run's cost or its rate-limit ceiling becomes the thing slowing iteration.**
