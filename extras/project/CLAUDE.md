# <PROJECT NAME> — working rules

Repo-specific rules only. The orchestration loop, model routing, agent roster, brief format
and reporting rules live in `~/.claude/CLAUDE.md` and the `orchestrator` output style, and
apply here too.

Keep this file about **this codebase**: how to check it, how to build it, what is dangerous
in it, and what it has already got wrong. Every line is re-paid by every subagent on every
spawn, so a line that would not change what Claude does is a line to delete.

---

## Commands — the gate agents run, and the ones they must not

| Purpose | Command | Measured |
|---|---|---|
| **FAST GATE — agents run this** | `<...>` | `<seconds — measure it, never guess>` |
| Full test suite (**I run this**) | `<...>` | `<...>` |
| Single test file | `<...>` | |
| Auto-fix lint | `<...>` | |
| Install · Build | `<...>` | |

**The FAST GATE line is the most important line in this file.** It must be diff-scoped,
**under ~60 seconds**, and contain **no test suite** — compile, analyzer, lint, type check,
secret scan, codegen staleness. Measure it once and write the real number.

If this line is missing, an agent invents a gate and picks the slowest command it can find.
Measured: one builder ran the full `pytest` suite **twice at 159 s each** — 5.3 minutes of a
17.8-minute run — purely because no fast gate was named here, while the project's own
`--fast` gate took **7.7 s**.

### Agents never run these

- **The full test suite.** Mine to run, once, at the end, when I ask. A builder runs only the
  test files its brief names; a review agent runs no checks at all — the gate's output is
  pasted into its brief.
- `<any DB advisor, migration, seed, deploy, or long-running audit command>` — name them here.
  Anything over ~60 s belongs on this list.
- If a command needs credentials or network an agent does not have, say so and name what the
  agent must report instead of a pass.

## Security surfaces in THIS repo

`~/.claude/CLAUDE.md` defines the general list. Name the concrete files and paths here, so a
reviewer does not have to guess. A change touching any of these is reviewed at once, never
batched.

- `<path>` — <auth / entitlement / RLS / upload / secrets / client-decidable rule>
- `<...>`

## Code navigation — the rule the guard does not enforce

Source is read and searched with **qartez**, never `Grep`/`Glob`/`Read` on code.

`qartez-guard` denies `Grep`, `Glob`, `Edit` and `Write` on source, **but it does not cover
`Read` or `Bash`** (verified: a `Read` on a `.py` file returns nothing from the guard). So an
agent blocked on `Grep` can still fall through to `Read` or `Bash grep` — and one measured
refuter did exactly that, pulling a 680-line file into its context in two chunks instead of
one `qartez_read` of the symbol. On those two tools the rule is the only thing stopping it.

`Read`/`Grep`/`Glob` are for non-code files: markdown, config, briefs. Markdown over ~300
lines goes through qmd windows, never a whole-file read.

## Layout

```
<dir>/     <one line — what lives here>
<dir>/     <one line>
```

Name the three or four files most changes touch, so a locate agent starts in the right place.

## Conventions

- <language/version, formatter, import style — only where it is not obvious from the code>
- New code matches the file it lands in: naming, idiom, comment density.

## Danger list

The things in this repo that cause real damage. One line each, direct.

- `<path>` — <what goes wrong if this is changed carelessly>
- <any command that writes to a live system, and who must authorize it>
- <any generated file that must not be hand-edited>

## Authorization

I authorize deploys, production writes, migrations, and anything touching a live system. An
agent that believes it needs one of these **stops and reports**.

## Task buckets

Multi-agent work uses buckets under `.claude/scratch/<slug>/`, opened by Claude when a task
starts or by `/task <sentence>`. Buckets are gitignored; nothing operational, no credentials
and no production data goes in them, or in any tracked doc.

## Handoff

`docs/HANDOFF.md` is the current session state — **read it at session start and verify it
before relying on it.** Check its recorded branch, HEAD and dirty-tree state against the repo.
Where the handoff and the repo disagree, **the repo is right**: correct the handoff and say
plainly that you corrected it. Replace stale state; never append a session log. Under ~100
lines.

Record: timestamp, branch, exact HEAD, dirty-tree state, current objective, material changes,
verification that actually ran with its real numbers, checks that did not run or failed,
unresolved decisions, known risks, the recommended next action, and what needs a human.

## Backlog

Every newly identified later action, deferred fix, investigation or dependency goes in
`docs/BACKLOG.md` before the response ends. Update the existing entry rather than duplicating
it. A chat message is not a record. Confirm it was written; if writing failed, say so instead
of claiming it is saved.

## Past defects — what this repo has already got wrong

Every entry is a rule added after a real defect, not a principle someone liked. Add to it
whenever a defect escapes review; the reviewer reads this list.

| # | Defect | Rule it earned |
|---|---|---|
| 1 | <what happened> | <the check that now catches it> |
