# STATE — <slug>

> **REPLACED, never appended.** This file says what is true NOW. History lives in
> FINDINGS.md, DECISIONS.md and git. If this file and the repo disagree, the repo is
> right — correct this file and say so. At most ~60 lines: longer means history crept in,
> so move it to FINDINGS.md. Same headings as the file `/task` seeds, plus the long-form
> extras below.

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

## User said
<!-- the user's own words, quoted: every approval, refusal, preference (also how to report
     results), worry and open question that exists only in the chat, each with its why in one
     clause. A worry is a requirement. -->

## Changed + verified
<!-- files touched · commit/sha · the check that proved each; a commit made after the
     handoff updates this before the turn ends -->

## Dead ends
<!-- tried · failed · why, so the next session does not retry it -->

## Unreviewed since <sha>
<!-- one line per small change done without agents: `path — what — why`.
     Orchestrator style: reviewed in ONE refuter pass when the first of these fires —
     commit time, 400 changed lines or 8 files accumulated, or the next builder change. A
     security surface is a builder + refuter at any size. Clear + advance the sha after. -->

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
