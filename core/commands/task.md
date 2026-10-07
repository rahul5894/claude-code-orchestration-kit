---
description: Task dashboard. With no words, lists every bucket and its next action. With a sentence, continues the matching bucket or opens a new one.
argument-hint: [what you want to do, in one sentence]
allowed-tools: Bash, Read, Write
---

Task request: **$ARGUMENTS**

A bucket is the folder `.claude/scratch/<slug>/` for one task. The index file
`.claude/scratch/INDEX.md` lists every bucket. Rules for buckets are in the kit's shared rules (`~/.claude/rules/orchestration-kit.md`).

## 1. Read the index

If `.claude/scratch/INDEX.md` does not exist, create it with exactly this content:

```markdown
# Task index
<!-- One line per bucket. Claude updates this whenever a bucket changes. -->
| slug | status | updated | next action |
|---|---|---|---|
```

Status is one of: OPEN, BLOCKED (waiting on me), DONE.

## 2. No words given: show the dashboard

Read the index. Report briefly:
- OPEN buckets with their next action.
- BLOCKED buckets and what they wait for.
- Anything marked DONE since the last session.

Then ask: continue one of these, or start something new?

## 3. A sentence given: continue or open

Compare the sentence to the OPEN and BLOCKED buckets.
- Same objective as an existing bucket: continue it (step 5).
- A different objective: open a new bucket (step 4), even if it touches the same files.
- Not sure: ask one question, "New task, or part of <slug>?", and wait.

## 4. Open a new bucket

1. Make the slug from the sentence: 2 to 4 words, lowercase, digits and hyphens only.
   "fix the ACL permission on the share page" becomes `acl-share-permission`.
2. Create `.claude/scratch/<slug>/` with these files and folders:

```
.claude/scratch/<slug>/
  STATE.md        replaced each update — what is true NOW
  FINDINGS.md     append-only — evidence, file:line
  DECISIONS.md    append-only — what changed and WHY
  briefs/         orders given to agents; written once, never edited
  reports/        one per brief
```

3. Seed the three files with exactly these headings and nothing else:

**STATE.md**
```markdown
# STATE — <slug>
<!-- REPLACED, never appended. History lives in FINDINGS/DECISIONS and git. -->
Updated: <date>   Status: OPEN
## Objective
## Repo
branch <x> @ <sha>, tree clean|N dirty
## Scope — in
## Scope — out
## Current subtask
## Next action
## User said
<!-- the user's words, quoted: decisions, preferences (also how to report results), worries, answers, constraints given only in chat -->
## Changed + verified
<!-- files touched · commit/sha · the check that proved each -->
## Dead ends
<!-- tried · failed · why, so the next session does not retry it; traps: a tool/command seen to break something here, with the evidence -->
## Active agents
| agent | brief | launched | ends when | running/terminal/unknown |
## Open questions
## Blockers
```
STATE.md is the handoff a fresh session resumes from. It must make the next session need
nothing from this conversation, in as few tokens as that takes:
- **Only what the next session cannot rebuild.** Never what `git status`/`git diff`, the code
  or a file already says; point at it instead (`install.ps1:87`, `FINDINGS:23`, `D007`), and
  at any doc that already holds analysis done here, so it is not redone.
- **What exists only in the chat goes under User said, quoted in the user's own words**: every
  approval, refusal, preference (how to work and how to report results), worry and pending
  question, each with its why in one clause. A worry ("must not stall at 95% again") is a
  requirement. It is the one
  thing no file can give back; a cold-read test found the whys the part most often missing.
- **No line contradicts another.** Rewrite from the last STATE.md: a fact that changed is
  rewritten where it stands; the old one is deleted, never left beside the new one.
- Fragments, not sentences. `→` for cause, numbers instead of adjectives. Paths, commands,
  errors, IDs and numbers are copied exactly, in backticks, never shortened or paraphrased.
  A trap or fix is written as it was seen, never inferred. One fact once: a finding or
  decision is cited by its line or ID, never restated.
- **Anything done after the handoff** (a commit, a push, a test run) updates Repo and
  Changed + verified before the turn ends.
- Done work that no next step depends on is dropped; FINDINGS, DECISIONS and git keep it.
- **At most ~60 lines** for a 45% handoff; the Stop hook's note sizes a fuller session's (80
  lines at 60%, 100 at 70%, 120 at 80%+). Longer means history crept in: move it to FINDINGS.
- **A handoff the Stop hook asked for has a session digest** beside it: the whole
  conversation, every user message and answer verbatim, written by the kit, not by you. Put
  `Digest: <path from the hook's note>` under Repo. STATE.md stays the curated snapshot: cite a
  digest turn (`digest T12`) instead of restating a long quote, never instead of a decision,
  a requirement or the next action.
- Before `/clear`, check it answers alone: what is the goal · what is done and how was it
  proven · the exact next action · what must not be retried · what the user decided or still
  has to decide. A gap is a line to add; a line that answers none of them is a line to cut.

**FINDINGS.md**
```markdown
# FINDINGS — <slug>
<!-- Append-only. Land here WHEN DISCOVERED, not at end of session. -->
<!-- Each: - <date> [gotcha|dead-end|fact|measure] what · file:line · evidence · what tested it (or "nothing tested this") -->
```

**DECISIONS.md**
```markdown
# DECISIONS — <slug>
<!-- Append-only. READ BEFORE ANY CHANGE. -->
<!-- Each: chose · rejected · WHY · reverses D0NN (an earlier decision's number) or nothing · files touched -->
```

4. Add one line for the bucket to the index.
5. Tell me in one line: "Opened bucket <slug>." Then show the objective and the proposed
   scope in and out. **Wait for me to confirm the scope** before starting the work.

## 5. Continue a bucket

1. Read `STATE.md` and `DECISIONS.md` whole. In `FINDINGS.md` skip only the `[fact]` and
   `[measure]` lines STATE does not cite (`grep -vn "\[fact\]\|\[measure\]" FINDINGS.md | cut -c1-2000` shows the rest;
   the wide cap keeps an entry's evidence, which `cut -c1-300` would drop);
   `[gotcha]`, `[dead-end]` and untagged older lines are always read. It is append-only, so
   a cited line number never moves.
   Then the **session digest** - the one STATE.md names under `Digest:`, else the one the
   session-start note names - **whole**: it is the previous conversation word for word, so
   Read it to the end, every window (each Read's notice gives the next offset), before you act.
   Measured on 4 real handoffs: STATE.md alone answered 63% of what the next session needed,
   STATE.md + digest 95%. Where the two disagree, the later turn wins; where the repo
   disagrees with either, the repo wins.
2. **Verify before trusting.** Check the recorded branch and HEAD against
   `git rev-parse --abbrev-ref HEAD`, `git rev-parse --short HEAD`, `git status --short`.
   Where the file and the repo disagree, **the repo is right**: correct the file and say
   that you corrected it.
3. Check `briefs/` against `reports/`. **Every brief must have a report.** A brief with no
   report means that agent never reported. List it as UNKNOWN, never as "nothing found".
4. Report briefly: objective, what is settled, what is open, unreported briefs,
   and the single next action. Then do the next action.

## While a bucket is open

- **A bucket is a handoff, not a delegation mode.** Unless the `orchestrator` output style
  is on, do the work yourself and spawn builder, refuter, verifier or debugger only when I
  ask. Briefs already in `briefs/` are history, not a pattern to continue.
- When you do spawn, write the brief to `briefs/<NN>-<task>.md` first. NN counts up from 01.
  Make it read-only (`attrib +R` on Windows, `chmod a-w` elsewhere). Do not show me
  briefs unless I ask.
- Every brief must name the bucket and require the agent to read `DECISIONS.md` before
  changing anything, append to `FINDINGS.md`, and never edit anything under `briefs/`.
  **Agents do not write `STATE.md`** — two writers to a replaced-not-appended `STATE.md` lose
  each other's content. A builder writes its own `reports/<NN>-builder.md`.
- Record the launch in `STATE.md` under Active agents. When the agent returns, mark it
  terminal; for every agent but the builder, **write `reports/<NN>-<agent>.md` yourself from
  its final message** (the SubagentStop hook also files it under `.claude/scratch/_inbox/`).
- Update the bucket's line in the index whenever its status or next action changes.
- If two rounds start swapping between the same two fixes, **stop the loop**, read
  `DECISIONS.md` yourself, and sort it out with me. Do not let it run.

## Closing

When the objective is met (its checks pass; if a review ran, the refuter returned no
candidates or the verifier marked every forwarded item FIXED; and nothing is open in `STATE.md`), or I say the task is abandoned:

1. Set `STATE.md` status to `CLOSED <date>` with a two-line outcome summary.
2. Write anything that outlives the task into the project's handoff note and backlog
   (see the project `CLAUDE.md`). Recording a follow-up never authorizes doing it.
3. Move `.claude/scratch/<slug>/` to `.claude/scratch/_closed/<slug>/`. Never delete a
   bucket.
4. Mark the bucket DONE in the index. Tell me in one line.

Do not close if any brief has no report, or if the agent count in `STATE.md` does not
balance (`launched = terminal + running + unknown`). Say which, and stop.
