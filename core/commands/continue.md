---
description: Resume the open task after /clear - reads its handoff (STATE.md) and carries on with the next action. With a slug, resumes that bucket.
argument-hint: [optional: bucket slug]
---

Resume work. Bucket: **$ARGUMENTS**

- Empty: follow the session-start note's marks, in this order.
  1. `(this window's task)`: what this window worked on before `/clear` - resume it, do not ask.
  2. `(open in another window)`: a parallel window is on it - never take it unless named.
  3. Of the rest (open, `STATE.md` not `Status: CLOSED`): one left - resume it; two or more -
     **recommend one** with a one-clause reason: `P1` on its row first; then the one nearest
     done or with the most concrete next action; then a BLOCKED one the user can unblock with
     one answer now; ties: `(newest handoff)` (in 9 of 12 measured resumes the user picked the
     newest). Ask in one question, the recommended one first, each with its next action.
  No note: same rule over `.claude/scratch/INDEX.md`, newest by the files' modification times.
  Say in one line which bucket you resumed and name the other open ones, then go on. None
  open: say there is nothing to resume.
- Then invoke the `task` skill with that slug as its argument; its "Continue a bucket" step
  reads the handoff, checks it against git, and does the next action.
