---
description: Resume the open task after /clear - reads its handoff (STATE.md) and carries on with the next action. With a slug, resumes that bucket.
argument-hint: [optional: bucket slug]
---

Resume work. Bucket: **$ARGUMENTS**

- Empty: of the OPEN or BLOCKED rows of `.claude/scratch/INDEX.md`, the bucket whose
  `STATE.md` was modified last - the handoff just saved (`ls -t .claude/scratch/*/STATE.md`).
  Do not ask which: in 9 of 12 measured resumes the user was asked and picked that one every
  time. Say in one line which bucket you resumed and name the other open ones, then go on.
  None open: say there is nothing to resume.
- Then invoke the `task` skill with that slug as its argument; its "Continue a bucket" step
  reads the handoff, checks it against git, and does the next action.
