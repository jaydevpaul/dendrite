---
description: End-of-session wrap-up — update the CLAUDE.md progress log and flag any decisions that touch LOCKED items in the decision record
---

Close out this session in two steps. Do not skip either one, and do not
merge them — the progress log update is a direct edit, the LOCKED check is
a proposal-only conversation with the user.

## 1. Update the Progress log in `CLAUDE.md`

Review this session's conversation and diff/tool history to determine:
- What was actually built or changed this session (be concrete: files,
  models, tables, folders — not vague summaries).
- Any decisions made along the way that aren't already captured elsewhere
  in CLAUDE.md.
- What the natural next step is, so a future session can pick up cleanly.

Edit the `## Progress log` section at the bottom of `CLAUDE.md`:
- Replace the `(empty — first session)` placeholder if this is the first
  entry, otherwise append a new dated entry below existing ones (don't
  overwrite prior sessions' logs).
- Date the entry using the current date.
- Keep it terse — a few bullet points, not prose paragraphs.

This edit happens automatically; no need to ask permission for this part.

## 2. Flag decisions that touch LOCKED items — propose, don't edit

Read `docs/Dendrite_Decision_Record.md` and identify every passage marked
LOCKED (e.g. "(LOCKED)" annotations, section 9 schema, locked stack
choices, immutable topology rules, etc.).

Cross-reference against what happened this session. For each decision
made this session that conflicts with, changes, or narrows a LOCKED item:
- Quote or point to the specific LOCKED passage it touches (with a
  section/line reference).
- Describe the decision made this session in one or two sentences.
- Ask the user explicitly whether this should be written into the decision
  record as a superseding entry.

Present these as a numbered list, one question per conflicting decision.
If nothing this session touched a LOCKED item, say so plainly and stop —
do not manufacture conflicts to fill out the list.

Under no circumstances edit `docs/Dendrite_Decision_Record.md` as part of
this command. It is read-only here — flagging and asking only. Any edit to
that file happens only after the user explicitly confirms, in a separate
follow-up action.
