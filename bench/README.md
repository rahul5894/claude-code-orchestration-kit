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
| `ref/<t>/`, `naive/<t>/` | files copied over the fixture's `shop/` to prove the tests: ref passes all, naive fails some |
| `score.py <repo> --ticket <t>` | one JSON line: spec, bugs, robust, security P/T, LOC added/removed, files changed under the package, and `quality` |
| `variants/` | alternative project `CLAUDE.md` files for `run_arm.py --claude-md` (e.g. a gate with linters) |
| `run_arm.py` | one arm, one ticket: clone, run `claude -p`, score, save `results/` |
| `results/` | gitignored: one `.json` + `.patch` per run |

## Arms

- **plain** — `claude -p --safe-mode`: no CLAUDE.md, hooks, MCP servers or agents (verified).
  Not `--setting-sources project` (it still loads `~/.claude/CLAUDE.md`) and not `--bare` (it
  needs an API key).
- **lean** — a normal `claude -p` with the kit installed and `outputStyle` = `kit-lean`.
- **full** — the same with `outputStyle` = `orchestrator`.

```
python bench/run_arm.py --arm plain --ticket refunds --effort high --tag a
python bench/run_arm.py --arm lean  --ticket refunds --tag a
python bench/run_arm.py --arm full  --ticket refunds --tag a --timeout 3600
```

`--style-file PATH` tries an unreleased output style: it is copied into the clone's
`.claude/output-styles/` and its frontmatter `name` becomes the arm's `outputStyle`.
Another model: `--model claude-fable-5-5` (the same flag for every arm).

## Quality metrics

`score.py` measures what an arm ADDED, as a delta against the untouched fixture, with the
tools in `bench/.venv` (`python -m venv bench/.venv`, then `pip install ruff vulture radon
pylint`; without it `quality` says SKIPPED):

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
2. `hidden/<t>/test_spec.py` — import `shop` from the path in env `BENCH_REPO`; catch the
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
