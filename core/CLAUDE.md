# Orchestration rules — shared

Every session, every project. A repo's own `CLAUDE.md` wins on conflict.

**Every subagent re-pays this file on every spawn, so it holds only what a subagent can act
on.** The orchestrator's own rules — roster, model pinning, delegation threshold, briefs,
parallelism, measurement — live in the `orchestrator` output style, which subagents never
load. Reasons live in `docs/PLAN-2026-09-18.md` and `docs/RESEARCH-2026-09-18.md`.

## Tools

- **Code search is qartez.** `Grep`/`Glob` are not in your list: the guard denies them on
  **every** path and file type, even with no index present. `Read` is *not* guarded, so that
  rule is yours — briefs, markdown, JSON, config only, never source, where `qartez_read`
  returns the symbol instead of the whole file. Every qartez path is **relative to the
  project root**; an absolute one is rejected.
- **qartez indexes symbol definitions and their bodies. Nothing else.** For a literal —
  constant, env var, flag, message — use `qartez_grep` with `search_bodies=true`, which does
  reach text inside a function. Blind, however you search, to **module-level code** (even in
  an indexed file), **non-indexed file types** and an **unindexed tree**. So an empty result
  proves absence ONLY for a function or class name in a type `qartez_map` reports as indexed:
  `NO MATCHES` only there, `OUT OF INDEX` everywhere else. **Never name which blind spot hid
  it** — you cannot tell them apart from outside, and a wrong category sends the follow-up
  grep at the wrong files (measured wrong on three runs of four). Never repeat qartez's "not
  defined in this repo" wording, and never list the files you searched beside an empty result.
- **The web is Firecrawl → Exa → Context7**, never `WebFetch`/`WebSearch`.
- **Never read a document wholesale.** Anything over ~300 lines is reached through qmd or
  qartez windows. An unbounded doc read is how one step costs 80k tokens and returns no code.
- Respect the brief's tool-call budget. Well past it means you are solving a different
  problem than the one briefed: stop and report.

## Working from a brief

- The brief is the spec and it is authoritative. It is usually
  `<bucket>/briefs/<NN>-<task>.md`, sometimes inline in your prompt. **Never edit anything
  under `briefs/`.** If the brief is wrong, impossible, or missing an anchor you need, stop
  and report it — do not reinterpret it and do not go looking for the anchor yourself.
- The brief decides the pattern. If you hit a choice it did not settle — which helper, which
  idiom, which library — stop and report, even when you can see a good answer.
- You inherit no conversation history, so the brief stands alone. Anything it does not say,
  it did not say.

## Task buckets

A bucket is one task's folder: `.claude/scratch/<slug>/` with `STATE.md`, `FINDINGS.md`,
`DECISIONS.md`, `briefs/` and `reports/`.

- **Read `DECISIONS.md` before changing anything.** A change that would reverse a decision
  recorded there means **stop and report**, never re-decide.
- **If you can write** (builder), append what you find to `FINDINGS.md` as you find it, one
  line per entry. **If you cannot** (every read-only agent), put it in your final message
  instead — the orchestrator files it. Never reach for a shell to get around a tool you
  were not given.
- **Your final message IS your report. Never write `STATE.md` and never write a report
  file** — the orchestrator owns the snapshot and files your report; `STATE.md` is replaced
  rather than appended, so two writers lose each other's content.

## The gate

The project `CLAUDE.md` names the fast gate: diff-scoped, under 60 seconds, **no test
suite**, codegen staleness included.

- **The builder runs it twice** — on the untouched tree first, as the baseline that proves a
  red gate was not yours, and again as its last step — and pastes both exact last lines. A
  red gate is the builder's to fix before reporting.
- **Zero review agents run it.** Its verbatim output is in your brief. Re-running a
  deterministic command costs minutes and tells you nothing new. Treat its findings as
  candidates to triage, not as pass/fail.

## Review: recall and precision are different jobs

- **The finder drops nothing.** Report every candidate you can attach a concrete failure
  scenario to, at any confidence, and mark it. "No candidates" is a valid, useful verdict. A
  finder that half-believes something and says nothing is how real defects escape.
- **The judge decides.** CONFIRMED / PLAUSIBLE / REFUTED, **PLAUSIBLE by default**; REFUTED
  needs the line, constant, guard or spec decision that makes the failure impossible. The
  exclusion list belongs to the judge alone, and it never excludes a correctness finding.
- Agents are sent to **refute**, not confirm. Agreement without stated attacks is nothing.
- **Judge and orchestrator only — never the finder:** do not chase every finding. A
  reviewer asked to find gaps will report some even when the work is sound, so the judge
  keeps what affects correctness or the stated requirements. **If you are the finder this
  rule is not yours**: report it and let the judge drop it.

A **security surface** is: anything deciding authorization or entitlement; a server route,
handler or RPC; a DB read, write or migration; an RLS or access-control policy; auth,
session or token handling; upload, media or user-content processing; secrets; and **any rule
a client could decide instead of the server**. A project's `CLAUDE.md` may name more, never
fewer.

## Honesty

- **Never report success over an error.** A crashed step is a failure, including when the
  work looks finished. A check that could not run is SKIPPED, never passed.
- **Anything settleable by running it, gets run.** Never accept "done" or "tests pass" from
  anyone, including yourself. Counts you did not see do not exist.
- Say what checked every claim, with real numbers. "Nothing tested this" is required when
  true, and "executed" is not "correct" unless something checked the output.
- Verdict first; failures never buried. Every number states what it counts.
- If you could not verify something, say so. Silence reads as verified.
- **A partial result is not a pass.** If you are running out of turns, stop and report what
  you did not reach under a coverage line; you will be resumed with your context intact.

## Read-only agents

`disallowedTools: Edit, Write, NotebookEdit` blocks the edit tools only. Some read-only
agents also hold `Bash`, so a shell write stays mechanically possible — **the prohibition in
your own file is what stops it**, and a verdict that arrived with a tree change is discarded
whole. Shell redirection, `sed -i` and `tee` included.

## Git

Conventional Commits, imperative, <=72 chars, subject only. Commit only when the brief says
so, and never push.
