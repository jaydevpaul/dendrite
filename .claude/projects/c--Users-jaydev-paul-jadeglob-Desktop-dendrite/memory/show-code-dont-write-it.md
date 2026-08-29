---
name: show-code-dont-write-it
description: On the dendrite project, output code in chat for the user to type manually instead of editing files
metadata:
  type: feedback
---

For the dendrite project, do NOT create or edit application code files.
Output the code in chat instead, and let the user type it in by hand.

**Why:** Dendrite is a learning project — the user's stated objective is to
learn coding and the concepts in depth, not just to end up with a working
repo. Typing the code is part of that. Stated 2026-08-02.

**How to apply:** Present each file's code in a fenced block with its path,
in build order, and explain what it does and why. Wait for the user to type
it before moving on.

Scope of the rule (refined 2026-08-21): it covers **application code under
`app/`**. Test files are exempt — the user asked me to create those
directly rather than type them. Docs the user asks to be saved (design
docs, decision record, progress log) are written directly too.
Verification commands are fine to run once the code is in place.
See [[dendrite-learning-project]].
