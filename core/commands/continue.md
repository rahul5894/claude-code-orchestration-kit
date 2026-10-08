---
description: Resume the open task after /clear - reads its handoff (STATE.md) and carries on with the next action. With a slug, resumes that bucket.
argument-hint: [optional: bucket slug]
---

Resume work. Bucket: **$ARGUMENTS**

- Empty: follow the session-start note's marks, in this order.
  1. `(this window's task)`: what this window worked on before `/clear` - resume it, do not ask.
  2. `(open in another window)`: a parallel window is on it - never take it unless named.
  3. Of the rest (open, `STATE.md` not `Status: CLOSED`): one left - resume it; two or more -
     ask which in one question, each with its next action, `(newest handoff)` first (in 9 of
     12 measured resumes the user picked the newest).
  No note: same rule over `.claude/scratch/INDEX.md`, newest by the files' modification times.
  Say in one line which bucket you resumed and name the other open ones, then go on. None
  open: say there is nothing to resume.
- Then invoke the `task` skill with that slug as its argument; its "Continue a bucket" step
  reads the handoff, checks it against git, and does the next action.
