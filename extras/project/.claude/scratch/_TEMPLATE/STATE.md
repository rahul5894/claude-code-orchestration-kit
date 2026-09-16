# STATE — <slug>

> **REPLACED, never appended.** This file says what is true NOW. History lives in
> FINDINGS.md, DECISIONS.md and git. If this file and the repo disagree, the repo is
> right — correct this file and say so.

**Updated:** <YYYY-MM-DD HH:MM>
**Status:** OPEN | BLOCKED | CLOSED <date>

## Objective
<one sentence>

## Repo
- Branch: `<branch>`
- HEAD: `<short sha>`
- Tree: `clean` | `<N> dirty` — <files>

## Scope — in
- <exact files / areas this task may touch>

## Scope — out
- <explicitly excluded, so an agent cannot wander into it>

## Current subtask
<one line, or `not started`>

## Next action
<the single next thing, concrete enough to act on cold>

## Unreviewed since <sha>
<!-- one line per small change done without agents: `path — what — why`.
     Reviewed in ONE refuter pass at commit, at 3 changes / 5 files, with the next builder
     change, or at once if a security surface is touched. Clear + advance the sha after. -->

## Active agents

| Agent | Brief | Launched | Ends when | State |
|---|---|---|---|---|
| <name> | briefs/<file> | <time> | <terminal condition> | running / terminal / unknown |

Accounting: `launched N = terminal N + running N + unknown N` — **balances / DOES NOT
BALANCE**. Anything unplaceable is `unknown`, never zero.

## Open questions
- <question> — <who or what settles it>

## Blockers
- <what is stopping progress, and what would clear it>

## Needs a human
- <decisions or authorizations only the operator can give>
