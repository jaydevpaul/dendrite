---
name: dendrite-learning-project
description: Dendrite's goal is learning depth plus a resume-worthy project, not just shipping working code
metadata:
  type: project
---

Dendrite is a learning project. The user's two stated objectives, in their
words: build something resume-worthy, and "learn things in detail." Stated
2026-08-02.

**Why:** This changes what "done" means. A correct implementation that the
user does not understand is a failure by their standard.

**How to apply:** Before building a layer, present the design, the
architecture, and the flows, and get agreement — the user asked for exactly
this before the auth layer and it worked well. Explain the *why* behind
each choice, including honest tradeoffs and the reasoning that is usually
skipped (e.g. why argon2 rather than SHA-256, why a stateless JWT's usual
selling point does not actually apply here). Do not just state a
recommendation; teach the concept underneath it. Pair with
[[show-code-dont-write-it]].
