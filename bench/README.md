# bench — plain Claude Code vs the kit, on the same ticket

A reproducible way to answer "does the kit pay for itself?" for a given model: every arm gets
the same ticket in a fresh clone of the same small repo, and hidden tests the arm never sees
score the result.

## Layout

| Path | What |
|---|---|
| `fixture/` | the base repo every arm starts from (a small stdlib order service) |
| `fixture-<t>/` | a ticket's own base repo when it has one (`billing`: a legacy service with seeded bugs and a `check.py`) |
| `tickets/<t>.txt` | the prompt, given verbatim to every arm |
| `hidden/<t>/test_spec*.py` | what the ticket asks for |
| `hidden/<t>/test_robust*.py` | robustness classes the ticket implies (bad input, never crash) |
| `hidden/<t>/test_security*.py` | who may do what, hostile input (optional group) |
| `hidden/<t>/test_bugs*.py` | defects seeded in the fixture's own code that the ticket asks the arm to find (optional group) |
| `ref/<t>/`, `naive/<t>/` | files copied over the fixture's package (`shop/`, or `billing/` for `fixture-billing`) to prove the tests: ref passes all, naive fails some |
| `score.py <repo> --ticket <t>` | one JSON line: spec, bugs, robust, security P/T, LOC added/removed, files changed under the package, and `quality` |
| `variants/` | alternative project `CLAUDE.md` files for `run_arm.py --claude-md` (e.g. a gate with linters) |
| `run_arm.py` | one arm, one ticket: clone, run `claude -p`, score, save `results/` |
| `collect.py <tag-prefix>` | one JSON line per run and a median per arm; for billing it also probes the clone for the `staff:` email hole |
| `mutate.py <clone> --ticket <t>` | how much the arm's OWN tests protect its code: seeds one bug at a time, counts the ones the hidden tests call real and the arm's tests caught |
| `results/` | gitignored: one `.json` + `.patch` per run |

## Arms

- **plain** — `claude -p --safe-mode`: no CLAUDE.md, hooks, MCP servers or agents (verified).
  Not `--setting-sources project` (it still loads `~/.claude/CLAUDE.md`) and not `--bare` (it
  needs an API key).
- **lean** — a normal `claude -p` with the kit installed and `outputStyle` = `kit-lean`.
- **full** — the same with `outputStyle` = `orchestrator`.
- **base** — `--setting-sources project,local --strict-mcp-config` with CLAUDE.md and auto
  memory switched off by env: the plain arm for testing a plugin, because `--safe-mode` also
  drops the hooks of `--plugin-dir` (verified 2026-10-08: no kit agent, skill or MCP server).
- **kit** — the installed kit exactly as the user runs it: no `outputStyle` override.

`--plugin-dir PATH` loads a plugin for the arm (base, kit, lean, full), e.g. a ponytail checkout.

```
python bench/run_arm.py --arm plain --ticket refunds --effort high --tag a
python bench/run_arm.py --arm lean  --ticket refunds --tag a
python bench/run_arm.py --arm full  --ticket refunds --tag a --timeout 3600
```

`--style-file PATH` tries an unreleased output style: it is copied into the clone's
`.claude/output-styles/` and its frontmatter `name` becomes the arm's `outputStyle`.
Another model: `--model claude-fable-5-1` (the same flag for every arm).

## Quality metrics

`score.py` measures what an arm ADDED, as a delta against the untouched fixture, with the
tools in `bench/.venv` (`python -m venv bench/.venv`, then `pip install ruff vulture radon
pylint`; when its python cannot import them `quality` says SKIPPED). A venv is per machine:
one copied from another machine exists but cannot start, and before 2026-10-08 that read as
zero findings everywhere - and broke `check.py` in every billing clone.

- `lint_added` / `lint_codes`: ruff F (unused, undefined), B (likely bugs), SIM, UP (outdated
  syntax), C4, PERF, RET, PIE, C901 (a function over complexity 10).
- `lint_fixed` / `lint_introduced` / `lint_fixed_codes`: findings of the untouched fixture the arm
  removed, and findings in code it wrote (matched by file, code and message, not line). Since
  the billing bench the set also has DTZ, E711/E712/E722, PTH, FURB and BLE.
- `dead_code_added`: vulture findings at >= 80% (unused import or argument, unreachable code)
  plus unused private names. At 60% vulture calls every public function of a library dead.
- `duplicate_blocks_added`: pylint duplicate-code, 5+ similar lines.
- `functions_added`, `classes_added`: how much structure the change introduced.
- `cc_max_new`, `cc_mean_new`, `cc_over_10_new`: radon complexity of new or changed functions.

The checkout ticket's spec group also counts SELECTs: `orders.summaries` for 1000 orders may
issue at most 25 (a query per order is 1000).

## Fairness rules

- Same ticket text, same fixture, same model for every arm; a fresh clone per run.
- Hidden tests live outside the clone; the arm never sees them.
- At least 2 runs per arm — a single run is noise.
- Report cost (`total_cost_usd`), wall time and both scores together; a cheaper arm that
  scores lower has not won.

## Adding a ticket

1. `tickets/<t>.txt` — the prompt.
2. `hidden/<t>/test_spec.py` — import the fixture's package (`shop`, or `billing`) from the path in env `BENCH_REPO`; catch the
   import error so the untouched fixture scores `0/T` instead of crashing (copy the top of
   `hidden/refunds/test_spec.py`).
3. `hidden/<t>/test_robust.py` (optional) — robustness classes, written from the ticket only.
4. `ref/<t>/` and `naive/<t>/` — prove ref scores T/T, naive fails, the fixture scores 0/T.

## The lesson from v1

v1 of the refunds tests required a refund on a `new` (unpaid) order; refusing one (no
money captured yet) is a defensible reading the ticket left open, and v2 pays the order first. **A hidden test must not fail a
defensible reading of the ticket.** Where a robustness test goes beyond what the ticket
clearly says, its value is marked `judgement` in a comment, so the score can be read with
and without those cases.

## Baseline results (2026-09-23, Claude Code 2.1.280, Opus 5.5)

Scores after the fairness fixes (v2 status-neutral spec tests; no untestable length rule).
Cost is `total_cost_usd` from `claude -p --output-format json`; one row per run.

| Ticket | Arm | Spec | Robust | LOC added | Cost | Wall |
|---|---|---|---|---|---|---|
| refunds | plain medium | 17/17 | 4/7 | 164 | $0.40 | 86 s |
| refunds | plain high | 16/17, 17/17 | 4/7, 5/7 | 170, 161 | $0.61, $0.49 | 152 s, 110 s |
| refunds | kit-lean | 17/17, 17/17 | 7/7, 5/7 | 139, 133 | $1.97, $1.96 | 371 s, 328 s |
| refunds | orchestrator (full) | 17/17 | 5/7 | 120 | $2.93 | 548 s |
| report | plain medium | 15/15 | - | 70 | $0.29 | 65 s |
| report | plain high | 15/15, 15/15 | - | 75, 70 | $0.51, $0.44 | 109 s, 100 s |
| report | kit-lean | 15/15, 15/15 | - | 57, 56 | $0.84, $0.82 | 93 s, 136 s |
| report | orchestrator (full) | 15/15 | - | 62 | $1.14 | 203 s |

Reading it: every arm meets the spec; the kit arms write less code and kit-lean is the most
robust, at ~2x (report) to ~4x (refunds) plain's cost. About half of that is fixed: the kit
environment's first prompt is ~40K tokens against ~20K under `--safe-mode`. Two runs per arm
is a small sample; re-run before trusting a difference of one robustness test.

### Bench D: the checkout ticket (2026-09-24, 2.1.280, Opus 5.5, 9 runs in parallel)

A long ticket (coupons + checkout + API + a report that must not query per order). Hidden
tests: 26 spec, 9 robustness, 9 security. ref 26/9/9, naive 24/6/7, fixture 0/0/0.
`lean` = the installed kit (its effort is high); `lean + lint` = the same with ruff and vulture
added to the project's gate (`variants/CLAUDE.lint.md`).

| Arm | Tests (spec/robust/sec) | LOC added | Lint added | Max cc (new) | Mean cc | Wall | Cost |
|---|---|---|---|---|---|---|---|
| plain high | 26/9/9 | 328 | 2 | 17 | 5.2 | 246 s | $1.02 |
| plain **xhigh** | 26/9/9, 26/9/9 | 317, 305 | 2, 2 | 17, 16 | 4.9, 5.3 | 627 s, 549 s | $2.57, $2.31 |
| kit-lean (high) | 26/9/9, 26/9/9 | 283, 245 | 2, 3 | 27, 25 | 7.1, 8.6 | 417 s, 417 s | $2.32, $1.98 |
| kit-lean xhigh | 26/9/9, 26/9/9 | 247, 225 | 2, 2 | 23, 25 | 6.1, 7.4 | 455 s, 459 s | $2.30, $2.23 |
| **kit-lean + lint gate** | 26/9/9, 26/9/9 | 264, 269 | **0, 0** | **16, 14** | **5.2, 4.8** | **311 s, 288 s** | **$1.83, $1.60** |

Lint added = ruff findings the arm introduced: every arm but lean + lint left C901 (a function
over complexity 10) and UP017 (outdated `timezone.utc`). No arm added dead code or duplicate
blocks. Every `noqa` in every patch is E402 (import position, not measured), so the lint arm
fixed its findings rather than silencing them.

Reading it: every arm passes every hidden test, so this ticket separates arms on quality, time
and cost only. Against plain xhigh, kit-lean + lint gate wrote ~14% less code with zero lint
findings, in about half the wall time and at ~70% of the cost. kit-lean without linters writes
the least code but concentrates it: its largest new function is the most complex of any arm.
Caveats: n=2 per arm, all 9 ran at once (wall times share one machine), and the lint arm's
gate uses the same ruff rules the metric counts - which is the point of a gate, not a trick.

To test a new model (e.g. Fable 5.x), run the same rows with `--model <id>` and compare.

### Bench E: the billing ticket (2026-09-24, 2.1.280, Opus 5.5 xhigh for every arm)

A hard ticket on a legacy fixture (`fixture-billing/`): plan changes with proration, a
concurrent-safe billing run, a keyset-paged statement API, plus "fix every bug you find and
modernise the package". The fixture hides 13 docstring-contradicting bugs and 24 lint findings,
and ships a `check.py` (ruff F/E9, vulture, unit tests) that every arm must leave green, like a
project's own `check:all`. Hidden tests: 18 spec, 13 bugs, 6 robust, 8 security. ref 45/45,
naive 18/45, fixture 1/45. Wave 1 ran 6 arms at once; `lean-fix` (kit-lean with the report and
test rule, via `--style-file`) ran 3 at once, so its wall times had less contention.

| Arm | Hidden (45) | Wall s | Cost $ | Package LOC+ | Test LOC+ | Legacy lint fixed /24 | Bug list in report |
|---|---|---|---|---|---|---|---|
| plain xhigh | 45, 45, 45 | 1389, 831, 733 | 6.25, 3.56, 3.13 | 595, 572, 645 | 680, 666, 720 | 24, 24, 24 | 3/3 |
| kit-lean xhigh | 45, 45, 45 | 585, 765, 663 | 2.88, 3.83, 3.55 | 340, 409, 369 | 232, 248, 191 | 21, 24, 21 | 0/3 |
| kit-lean-fix xhigh | 45, 45, 45 | 847, 763, 860 | 4.41, 4.29, 4.66 | 366, 391, 425 | 303, 355, 327 | 24, 21, 24 | 3/3 |

Beyond the hidden tests (probed or read from the final messages): a customer email starting
`staff:` passes as staff - closed by plain 1/3, kit-lean 2/3, kit-lean-fix 1/3. A customer can
farm credit by backdating `on` (upgrade late, downgrade early, repeat) - flagged by kit-lean 5/6
runs (its `/security-review`), plain 0/3; nobody fixed it because the ticket allows it. Savepoint
nesting / new indexes / dataclasses: plain 3/3, 3/3, 2/3; kit-lean(+fix) 1/6, 2/6, 0/6.

Reading it: correctness ties again (every run 45/45: Opus 5.5 xhigh alone clears this ticket).
kit-lean-fix against plain: median wall +2%, cost about equal, ~35% less package code, half the
test code, same report. Its edge is spotting business-logic abuse; plain's is more tests and
more database hardening. The "report is my own last message" rule (kit-lean.md step 7) fixed
the lost bug list 3/3. n=3 per arm.

**Wave G (2026-09-24): ponytail uninstalled, all 9 runs at once.** The kit-lean rows above ran
with the user's ponytail plugin loaded (its SessionStart rules: shortest diff, "YAGNI applies to
tests"); plain (`--safe-mode`) never had it. With it gone, the same ticket again, plus
`kit-lean-v2` (`bench/variants/kit-lean-v2.md`: both reviews in parallel, and a trust-boundary
sweep of the code the ticket hands over, not only the diff).

| Arm | Hidden (45) | Wall s | Cost $ | Package LOC+ | Test LOC+ | Legacy lint fixed /24 | `staff:` email closed | Credit farming flagged |
|---|---|---|---|---|---|---|---|---|
| plain xhigh | 45, 45, 45 | 1321, 839, 704 | 5.76, 3.18, 2.93 | 605, 496, 570 | 638, 663, 591 | 24, 24, 24 | 2/3 | 0/3 |
| kit-lean xhigh | 45, 45, 45 | 856, 1073, 894 | 4.71, 4.91, 4.29 | 526, 499, 549 | 611, 605, 529 | 24, 21, 24 | 0/3 | 1/3 |
| kit-lean-v2 xhigh | 45, 45, 45 | 1011, 960, 997 | 5.02, 4.50, 4.98 | 535, 509, 544 | 559, 612, 681 | 24, 24, 24 | 1/3 | 2/3 |

Every run's final message carried the bug list. Reading it: without ponytail, kit-lean writes
as much package and test code as plain (the earlier "35% less code, half the tests" was
ponytail's doing). Median wall: plain 839 s, kit-lean 894 s (+7%), v2 997 s (+19%); mean cost
+17% and +22%. v2 caught one more of each probe than kit-lean, which at n=3 is within noise
(kit-lean flagged credit farming 1/3 here and 3/3 in an earlier ponytail-off wave). v2 was
not promoted: it missed the "time within plain +5%" bar and its catches are not separable
from noise. Correctness still ties (45/45 x9). `num_turns`/`duration_ms` in a run's JSON
cover only the last segment when the session woke on a background task; `wall_s` is the
harness's own clock.

### Bench F: Ponytail 5 (2026-10-08, Claude Code 2.1.288, Opus 5.5 xhigh for every arm)

Ponytail v5.0.0 (`b088b2d`) rewrote the rules that got v4 dropped after bench E: "the smallest
complete change", and non-trivial logic must leave a test. Four arms, each with and without it
through `--plugin-dir`: `base`, `base` + PT, `kit`, `kit` + PT. Billing ran 5 times per arm:
wave 1 (12 at once) had `check.py`'s linters broken for every arm by a venv from another
machine, and wave 2 (2 per arm) had the venv rebuilt. Checkout ran 2 times per arm in wave 2.
Wave 1's quality metrics were re-scored offline. Values are medians.

`Own tests catch` comes from `mutate.py`: real bugs, meaning those the hidden tests kill, that
the arm's own tests also killed. Most runs used every mutation point or a 60-mutant sample.
Four kit + PT runs used 15 mutants. It covers 23 of the 28 runs. Five billing clones were not
measured: their clean hidden suite takes 11 s alone, but over 2 minutes with 9 clones
contending for sqlite locks at once.

| Ticket | Arm | Hidden | Wall s | Cost $ | Package LOC+ | Test LOC+ | Own tests catch | `staff:` hole closed |
|---|---|---|---|---|---|---|---|---|
| billing | base | 45/45 x5 | 997 | 3.88 | 588 | 766 | 285/286 (3 runs) | 4/5 |
| billing | base + PT | 45/45 x5 | 551 | 2.14 | 353 | 234 | 447/480 (4 runs) | 2/5 |
| billing | kit | 45/45 x5 | 927 | 3.69 | 577 | 639 | 114/117 (3 runs) | 4/5 |
| billing | kit + PT | 45/45 x5 | 554 | 2.54 | 364 | 280 | 81/88 (5 runs) | 1/5 |
| checkout | base | 44/44 x2 | 1106 | 2.94 | 346 | 422 | 118/122 | - |
| checkout | base + PT | 44/44 x2 | 345 | 1.34 | 242 | 166 | 53/60 | - |
| checkout | kit | 44/44 x2 | 629 | 2.63 | 334 | 312 | 63/65 | - |
| checkout | kit + PT | 44/44 x2 | 371 | 1.64 | 232 | 142 | 52/59 | - |

How to read it:

- **Correctness ties.** Every one of the 28 runs passed every hidden test.
- **Ponytail's gains:**
  - wall time -40 to -69%
  - cost -31 to -54%
  - package code -30 to -40%
- **What it costs:**
  - **Fewer tests:** test code -54 to -69%.
  - **Weaker tests:** without Ponytail the arm's own tests caught 580 of 590 real bugs (98.3%); with it, 633 of 687 (92.1%). Bugs that slip past the arm's own tests go from 1.7% to 7.9%, and every pair moved the same way.
  - **Less beyond-spec hardening:** a customer registered as `staff:...` becomes staff. With Ponytail this was closed in 3 of 10 runs, without it in 8 of 10 (Fisher p=0.07).
  - **Denser code:** the most complex new function on checkout reached 24.5 with base + PT, against 17 with base.
  - **Some legacy lint left in place:** 6 of 10 Ponytail billing runs left 3 C408 findings (`dict()` calls, style only).
- **Ties:**
  - **Honesty:** every arm reported the broken gate in wave 1 and ended with its risks.
  - **Subagent use:** no kit arm spawned a subagent, so Ponytail's SubagentStart injection was never exercised.
- **The author's "injected bugs caught 66% vs 46%" does not reproduce here.** Their bench
  disables Bash, so the no-skill arm often wrote no test. At xhigh with Bash, every arm writes
  tests, and the arms without Ponytail write the stronger ones.
- **Kit without Ponytail:** about base's quality and slightly faster. With Ponytail, the kit
  adds about 20% to the cost.
- **Verdict:** the same trade as v4. The kit takes no side (2026-10-08, user decision): Ponytail
  is in `core/plugins.json` `allow`, so the kit neither installs nor disables it.

## Handoff and md-guard (2026-10-07, Claude Code 2.1.292, Opus 5.5)

`bench/handoff/` measures what reaches the NEXT session, not one ticket. Everything it writes
goes to `bench/results/` (gitignored: it holds other projects' conversations).

| Script | What it does |
|---|---|
| `mine_guard.py`, `classify_shell.py` | every md-guard denial in `~/.claude/projects`, why it fired, and what the agent read afterwards |
| `measure_digest.py` | the session digest's size at each real handoff point |
| `chains.py`, `prep.py`, `compact_fork.py` | real A→B handoff chains; the materials per arm, incl. Claude Code's own `/compact` run on a fork |
| `ab.py probes/read/grade/report` | 20 probes per chain from A's raw transcript, cold no-tool readers per arm, a blind grader |
| `guard_probe.py` | live `claude -p` runs: no guard / old / new md-guard on three doc tasks |

Handoff, 4 real chains × 20 probes × 2 readers (share of probes answered; tokens of the note):

| What the next session got | Score | Wrong | ~Tokens |
|---|---|---|---|
| nothing (/clear) | 0.0% | 0 | 0 |
| Claude Code `/compact` | 72.5% | 1 | 4.9K |
| kit STATE+DECISIONS+FINDINGS (before) | 63.4% | 2 | 5.0K |
| digest, words only | 85.3% | 0 | 45K |
| digest, words + output excerpts | 89.7% | 0 | 77K |
| kit + words-only digest | 91.9% | 2 | 50K |
| kit + full digest (shipped) | 94.7% | 2 | 82K |

md-guard, 3 tasks × 3 runs: every run correct under all three guards; the new guard costs
what no guard costs (whole spec 127K vs 123K tokens; brief 93K vs 108K) where the old one cost
166K and 122K. Real transcripts: after a deny the agent read the doc whole 0 of 14 times.

Round 2 the same day (old guard pinned to `d5da6a2`): whole spec none 93K, old 138K, window
144K; brief none 58K, old 92K, window 57K. With no Read guard cheapest or equal in both rounds,
and Claude Code's own Read paging a doc over 25K tokens with a PARTIAL-view note, the kit's Read
window was dropped (bucket kit-digest-review D005): md-guard now guards shell reads only.

After the review rework (same probes, fresh readers): kit + full digest 93.4%, 0 wrong (v1
94.7%, 2 wrong); digest alone 86.6% (v1 89.7%) - the content barely moved, the gap is reader
variance.

## Task timeline (2026-10-09, Claude Code 2.1.295, Opus 5.5; bucket handoff-timeline)

| Script | What it does |
|---|---|
| `chain_live.py [--arm old\|new]` | live, headless, only the hooks under test (`--setting-sources project --settings`): task alpha over 3 sessions + /clears, task beta in a parallel window that is KILLED; 10 checks on the records |
| `dense_ab.py` | the 4 chains above, STATE.md rewritten "densest without loss" vs as written, same probes |
| `chain_ab.py prep/probes/read/grade/report` | real 4-8-session tasks; 10 "earlier-session" + 6 "any" probes; Opus readers with Read/Grep/Glob in a sandbox (the task's bucket + another task's as a distractor), old rules + 5 newest digests vs new rules + every record + SESSIONS.md; blind grader. `--arms new` (prep, read) rebuilds and re-reads one arm only, the other arm's answers kept as the baseline (round 4) |
| `note_writes_scan.py` | every shell command in `~/.claude/projects` that names a bucket note, judged by the old any-`>` write test and by `kit_index.shell_notes`; counts and samples of every disagreement (2026-10-10: 4,337 commands) |

| Test | Old kit | New kit |
|---|---|---|
| live chain test (checks passed) | 1/10 | 10/10 |
| step-back A/B, earlier-session facts | 63.3% | 97.5% |
| step-back A/B, all facts | 76.6% | 97.4% |
| confident wrong answers (of 96) | 0 | 1 (a python/python3 misread) |
| reader tokens per run | 3.28M | 3.54M |
| SESSIONS.md on the default /continue path | - | 749-1745 tokens |
| dense STATE rewrite: score / size | 62.8% / 100% | 63.8% / 97-103% (not adopted) |

Two harness traps on the way, both in `chain_ab.py`'s docstrings: `--max-turns 60` ended 3 of
16 runs with no answers (both arms), and counting every session that merely READ the bucket
gave the old arm another task's last session. Round 3 is the fair one.

**Rounds 4-5 (2026-10-10), after the fixes round 3's misses pointed to** - an error line now names
its command (the one wrong answer read "Exit code 49 Python was not found" with no command and
guessed `python` for `python3`), an ssh MCP's command is shown (747 of one task's server
commands were a bare tool name), a task notification is never the user's words, and a shell
command files a session under a task only when it WRITES that task's notes (`2>/dev/null` beside
a read had filed it under a closed one). Same 48 probes; 3 samples per arm. Round 5 also gives
each reader the project's MEMORY.md index, as every real session starts with it.

| Test | Old kit | New kit |
|---|---|---|
| r4 sandbox (old = r3): earlier / current-state / all | 63.3% / 98.6% / 76.6% | 95.6% / 98.1% / 96.5% |
| r4 confident wrong answers | 0 of 96 | 0 of 144 |
| r5 with MEMORY.md: earlier / current-state / all | 63.9% / 97.2% / 76.4% | 98.9% / 98.1% / 98.6% |
| r5 confident wrong answers (of 144) | 1 (the python/python3 swap) | 0 |
| r5 reader tokens / $ per run | 1.97M / $1.53 | 2.34M / $1.52 |

The current-state points both kits still lose are one detail (`QB_ARMS fixroot`) left out of a
short answer; it is in the current STATE.md. `note_writes_scan.py` holds the filing fix's own
measure: of 642 note writes the old test saw, ~167 were reads, and it never saw 389 real ones.
