---
description: Resume the open task after /clear - reads its handoff (STATE.md) and carries on with the next action. With a slug, resumes that bucket.
argument-hint: [optional: bucket slug]
---

Resume work. Bucket: **$ARGUMENTS**

- Empty: the one OPEN or BLOCKED row of `.claude/scratch/INDEX.md`. Several and none named:
  ask one question listing them. None: say there is nothing to resume.
- Then invoke the `task` skill with that slug as its argument; its "Continue a bucket" step
  reads the handoff, checks it against git, and does the next action.
