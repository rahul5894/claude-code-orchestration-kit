# Ponytail - ready to switch on, not switched on

Status 2026-10-08: **off**. The user decided to keep running the kit as before. Follow this file
only when the user says to install Ponytail. Until then nothing here is applied:
`core/plugins.json` keeps `ponytail@ponytail` in `disable`, and `install.ps1` turns it off if it
appears.

## What it changes (bench F, Opus 5.5 xhigh, full numbers in bench/README.md)

| Measure | kit | kit + Ponytail 5.0.0 | Change |
|---|---|---|---|
| Billing time / cost | 927 s / $3.69 | 554 s / $2.54 | -40% / -31% |
| Checkout time / cost | 629 s / $2.63 | 371 s / $1.64 | -41% / -38% |
| Output tokens (billing / checkout) | 94K / 65K | 62K / 40K | -35% / -39% |
| Hidden tests (spec, 13 seeded bugs, robust, security) | all, 7/7 runs | all, 7/7 runs | same |
| Package code (billing / checkout) | 577 / 334 lines | 364 / 232 lines | -37% / -31% |
| Test code (billing / checkout) | 639 / 312 lines | 280 / 142 lines | -56% / -54% |
| Real bugs the arm's own tests catch | 177/182 (97%) | 133/147 (90%) | worse |
| Beyond-spec `staff:` hole closed | 4/5 | 1/5 | worse |

It is faster and cheaper, with the same spec score. In exchange it writes fewer and weaker
tests and does less hardening beyond the spec.

## Before switching on

If Ponytail is newer than 5.0.0, re-run bench F first (about 30 min, all arms in parallel).
The arms here are the two that matter for the kit:

```
python bench/run_arm.py --arm kit --ticket billing --effort xhigh --tag ptNw1-kit-1 --timeout 3600
python bench/run_arm.py --arm kit --ticket billing --effort xhigh --plugin-dir <ponytail checkout> --tag ptNw1-kitpt-1 --timeout 3600
python bench/collect.py ptNw1
python bench/mutate.py <clone from the result json> --ticket billing --n 60
```

Run 3 or more per arm. Run mutate.py at most 4 clones at a time, because sqlite lock
contention slows the hidden suite 10x.

## Switching on (repo first, then the machine)

1. `core/plugins.json`: move `ponytail@ponytail` from `disable` to `allow`, and give the
   reason and the bench numbers.
2. `core/settings.user.json` `env`:
   - Add `"PONYTAIL_SUBAGENT_MATCHER": "^(builder|debugger)$"`, so only the code-writing
     agents get its rules and refuter, verifier and researcher stay unbiased.
   - For opt-in use, also add `"PONYTAIL_DEFAULT_MODE": "off"`. Ponytail then stays silent until
     `/ponytail` is typed, for that session only.
3. `install.ps1` line 39 `$RETIRED_ENV`: drop the ponytail entry. Otherwise the installer
   removes the pin that step 2 adds.
4. `validate_kit.py`: flip the two ponytail checks. Line 726 expects no matcher pin, and
   line 1189 expects ponytail in `disable`.
5. `verify_live.py` line 193 `_RETIRED_PIN`: it probes that install.ps1 removes this pin. Point
   the probe at another retired key, or drop that probe.
6. Run the gate, every self-test and `python verify_live.py`. Then commit and push.
7. On the machine, in Claude Code, send two separate prompts:
   `/plugin marketplace add DietrichGebert/ponytail` then `/plugin install ponytail@ponytail`.
   Then run `pwsh -File install.ps1`.
8. Check: start `claude -p "ok"` in an empty folder and grep its transcript in
   `~/.claude/projects/` for `PONYTAIL MODE ACTIVE`. Expect it once with the always-on setup,
   and no match with opt-in.

Expect a one-time prompt. With no `statusLine` set, its first session asks to set up a
`[PONYTAIL]` badge; it is safe to decline.

## Using it

- For auth, money, permissions or user input, say `stop ponytail` or keep the kit's review on
  that change. Those are the measured weak spots.
- `/kit-off` does not stop Ponytail. `stop ponytail` or `/ponytail off` does.

## Rollback

`/plugin remove ponytail`, `git revert` the switch-on commit, then `pwsh -File install.ps1`.
Delete Ponytail's state: in `~/.claude`, `.ponytail-active`, `.ponytail-statusline-nudged`,
`ponytail-statusline.ps1` and `ponytail-modes/`, plus `%APPDATA%\ponytail\`.
