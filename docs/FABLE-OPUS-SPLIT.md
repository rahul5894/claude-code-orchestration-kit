# Who does what: Fable 5.1 and Opus 5 in this kit

Written 2026-09-20 for Claude Code 2.1.276. This is the reference for "which seat does
which work", so that a new machine, a new project, or a new plugin lands on the same split.
The rules themselves live in `core/output-styles/orchestrator.md` and `core/CLAUDE.md`;
this page only explains the shape.

## The one sentence

Fable 5.1 sits in the main session and does every act of judgment. Opus 5 sits in the
subagents and does every act of execution. Haiku locates. Nothing else runs.

## What Fable does (the main session, `/model fable`)

Fable is the orchestrator. It is the only seat that:

- reads what you wrote and decides what "done" means;
- reads the code before anything is changed, and decides the design: which pattern, which
  helper, which file, which library;
- writes every brief (`briefs/NN-task.md`), with the base sha, the gate command and its
  real output, the exact files, and a tool-call budget;
- runs the fast gate itself for the baseline and again before recording a change;
- makes only trivial changes itself (under ~30 changed lines or ~2 files, no new logic, not
  a security surface); every other change is a builder, because each Fable turn re-reads the
  whole context (measured 422K cached tokens per turn, 2026-09-22);
- judges every review finding: CONFIRMED, PLAUSIBLE or REFUTED, with the line or the doc
  window that proves it (a verifier agent can do this too; Fable overrules it);
- runs `verify_live.py`, `install.ps1`, and anything else that writes to `~/.claude` or
  the machine; no subagent ever does;
- commits and pushes, only when you said so;
- owns the bucket: `STATE.md`, `DECISIONS.md`, `INDEX.md`, the reports.

The `debugger` agent is `model: inherit`, so a hard root-cause hunt also runs on Fable
while you are on Fable, and on Opus once Fable quota is gone. Nothing else inherits.

## What Opus does (every other subagent, pinned `opus` at `high`)

| Agent | Does | Never does |
|---|---|---|
| `builder` | Implements a brief that already names the pattern. Runs the gate first (baseline) and last. Reports with exact last lines. | Designs. Chooses a library. Runs the installer. Commits. |
| `refuter` | Finds every defect it can attach a failure scenario to, correctness and security, one pass. Measures by running the hooks or the code where it can. | Judges. Fixes. Runs the gate. Writes to the tree (md-guard denies it). |
| `verifier` | Judges a finder's list: CONFIRMED / PLAUSIBLE / REFUTED, FIXED / NOT FIXED after a rework. Carries the exclusion list. | Finds. Has no shell at all. |
| `researcher` | Reads source, library docs (Context7) and the web (Firecrawl, Exa) and reports facts with citations, UNVERIFIED where it could not. | Decides anything. Edits anything. |
| `Explore` (haiku) | Returns locations only, through qartez. | Reads file contents. |

## How a task is defined when Fable is selected

1. You say what you want. Fable reads the spec and the code, not a summary of either.
2. Fable opens one bucket per objective under `.claude/scratch/<slug>/`, writes
   `DECISIONS.md` (settled, not reopenable by agents) and `STATE.md`.
3. Small change: Fable edits, runs the gate, records the change under "Unreviewed since
   <sha>". Large change or security surface: Fable writes a brief and spawns a builder.
4. Every spawned agent receives the open bucket's `DECISIONS.md` at start (the
   `SubagentStart` hook injects it), so it cannot re-decide by accident.
5. Refuter finds, verifier or Fable judges, builder-02 fixes what was accepted. Three
   agents on the happy path, five at most.
6. Fable installs, probes the real thing once (a live agent, a real command), then commits
   on your word.

## Why the split saves Fable tokens

- Fable never builds, reviews, researches or locates: those are the long, tool-heavy turns
  (measured this week: a builder at 63 turns, a refuter at 26 tool calls). Fable's turns
  are short: read, decide, write a brief, judge.
- `Agent(model:fable)` is denied in settings, so no subagent can land on Fable by mistake.
- `CLAUDE_CODE_SUBAGENT_MODEL=opus` catches any off-roster spawn; `inherit` is only on
  the debugger.
- Fable is the worst seat to fan out from (measured 2m15s alone vs 17m00s with five
  subagents), so the delegation threshold keeps only trivial work inline.

## What "everyone works together" means here

- Plugins: `core/plugins.json` says which plugins may inject into every session and which
  are disabled; `verify_live.py` section C6 names any new one that is neither. A plugin
  that wants to change how replies read (simple-english) is shipped as a slash-only skill
  instead, so it runs only when you call it.
- Ponytail stays: its lazy-code rules are scoped to `builder` and `debugger` through
  `PONYTAIL_SUBAGENT_MATCHER`, and to the main session in full.
- qartez is the code search for every agent; `Grep`/`Glob` are denied everywhere. `OUT OF
  INDEX` means "grep the tree", never a reason.
- md-guard keeps big markdown behind qmd, and keeps `refuter` and `debugger` from writing.
- The gate is per project (`FAST GATE` row, written once by `/kit-init`); reviewers never
  run it, builders run it twice.

## Checking the split on a machine

```
python verify_live.py        # sections D (pins), C5 (projects), C6 (plugins)
python audit_project.py .    # this project's CLAUDE.md against the global rules
python agent_stats.py --since <date>   # which model ran which agent, turns, denials
```
