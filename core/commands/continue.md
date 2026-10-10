---
description: The one way to start or resume work. Alone, it resumes this window's task or recommends one of the open tasks. With a request, it routes it - to the open task it belongs to (the new instructions added), a closed task it continues (reopened), or a new task it opens itself - after one question. Decides from the task cards; reads the full history only of the task picked.
argument-hint: [optional: what you want to do now, or a task slug]
---

Request (blank = `/continue` alone): $ARGUMENTS

## 1. Decide from the task cards

The session-start note's block `orchestration-kit: task cards` holds one card per open task -
its own short description, as a skill has one: `about` (what it is), `state`, `next step`, when
it was last worked on, how many sessions - and the tasks closed in the last 14 days. At most 8
cards: this window's task first, then the most recently worked on; the rest are only named, in
one `(+N older: ...)` line. **Open no bucket file before the user has picked a task**: reading
every task to choose is the waste the cards exist to avoid. No cards in context, a task was
opened or closed since this session started, or a request may belong to a task that line only
names: run `python ~/.claude/hooks/kit-session-start.py --cards "<root>"` once (up to 20 cards;
`<root>` = the absolute primary working directory, never `.`) and decide from what it prints.
If it says the kit is off in this project (the default): tell the user, offer `/kit-on`, and stop.

## 2. No request: `/continue` alone, or a task's slug

- A slug: that task, no question.
- A card marked `(this window's task)`: what this window worked on before `/clear` - resume it
  without asking, and name the other open tasks in one line so the user can switch.
- A card marked `(open in another window)` is being worked there: never take it unless named.
- Of the rest: none open - say so and ask what to work on; one - resume it; two or more -
  **recommend one** with a one-clause reason: `P1` first; never an idle one (` · idle Nd` on its
  row: untouched over 14 days) over a fresh one unless it is P1; then the one nearest done or
  with the most concrete next step; then a BLOCKED one the user can unblock with one answer now;
  ties: `(newest handoff)` (in 9 of 12 measured resumes the user picked the newest). Ask (step 4).

## 3. A request: `/continue <what to do>`

Read it against every card - `about` first, then `next step` and `state` - open and closed:
- **Belongs to an open task**: the same objective or feature, with more to do, a change, a
  constraint ("also add X", "do not touch Y"), or the answer the task was blocked on. Sharing
  a file or a word is not enough: a different objective is a different task.
- **Continues a closed task**: the same feature, more work on it.
- **New**: belongs to none.
- **Ambiguous**: two or more fit.

Then ask (step 4) - also when one task clearly fits: the user confirms where a new instruction
goes. The options, the recommended one first:
- belongs to X: continue X with it · a new task instead · up to two other open tasks;
- continues closed X: reopen X · a new task;
- new: a new task `<slug>` - unless an open task is P1 or one step from done, then recommend
  finishing that first · finish <that task> first, the request saved as a queued task · just
  answer, no task - when the request is a question or a few minutes' work;
- ambiguous: each task that fits · a new task.

## 4. Asking

One AskUserQuestion call: at most 4 options; the recommended one first, with `(Recommended)` in
its label; each option's description says what happens next (the task's next step, or "opens
task <slug>"). More open tasks than fit: the best three, the rest named in the question - the
user can type one under Other. Anything typed under Other is a new request: route it from
step 3. No AskUserQuestion tool (a headless run): write the question with numbered options and
stop. Nothing else before the answer - no file edited, no command that changes anything.

## 5. After the choice

- **An open task**: invoke the `task` skill with its slug. Its "Continue a bucket" step reads
  that task's whole history - STATE, DECISIONS, FINDINGS, SESSIONS.md, the last session's
  record - and checks it against git. Never open another task's files. With a request: first
  quote it, dated, under `## User said` in that task's STATE.md; it is now the current step and
  overrides an older next step it conflicts with.
- **Reopen a closed task**: set its STATE.md `Status:` back to `OPEN` (`reopened <date>`) and
  its INDEX.md row to OPEN, then as above. Its verbatim records go 7 days after a close; STATE,
  DECISIONS, FINDINGS and SESSIONS.md stay.
- **A new task**: invoke the `task` skill with `new: <the request>` - it opens the bucket, its
  `About:` line made from the request, and starts without asking about the scope again.
- **Finish another first**: invoke the `task` skill with `queue: <the request>` - it opens the
  new task's bucket and does no work on it - then resume the other task as above.
- **Just answer**: answer it; no bucket.

Say in one line what you resumed or opened, and name the other open tasks.
