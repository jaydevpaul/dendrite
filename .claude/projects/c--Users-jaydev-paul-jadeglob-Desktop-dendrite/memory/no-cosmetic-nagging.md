---
name: no-cosmetic-nagging
description: User dislikes repeated reminders about trivial/cosmetic items
metadata:
  type: feedback
---

Don't repeatedly surface trivial, cosmetic non-issues (typos in filenames,
"confirm X is present" nits) that don't affect the project. Mention such a
thing once at most, then drop it unless asked.

**Why:** The user found repeated "Next: rename the typo / confirm the dep"
reminders annoying and told me to stop bringing them up.

**How to apply:** Offer a cosmetic cleanup once, briefly. If not taken up,
do not re-raise it in later messages or carry it forward in the progress
log's "Next". Reserve follow-ups for things that actually affect
correctness or the project's direction.
