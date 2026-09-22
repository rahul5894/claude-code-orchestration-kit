---
description: Set up the orchestration kit in THIS project. Detects the fast gate, times it, writes CLAUDE.md from the global template, then audits the project. Run once per new repo, or whenever the session-start notice says the FAST GATE row is missing.
argument-hint: [optional: the gate command, if you already know it]
allowed-tools: Bash, Read, Write, Edit
---

Set up this project for the orchestration kit. Everything else in the kit is already global;
the **only** thing a project needs is a `CLAUDE.md` with a measured FAST GATE row.

Argument (optional, the gate command if the user knows it): **$ARGUMENTS**

## 1. Never guess the gate — detect, then measure

Find candidate fast-gate commands from what the repo actually has. Read only these, and only
if they exist: `package.json` (`scripts`), `pyproject.toml` / `setup.cfg` / `Makefile`,
`go.mod`, `pubspec.yaml`, `Cargo.toml`. Candidates are, in order of preference:

- an existing script or target whose name contains `check-fast`, `lint`, `check`, `typecheck`,
  `analyze`, `vet`, `clippy`, `fmt-check`
- otherwise the stack's native fast check: `ruff check . && mypy .`, `npx tsc --noEmit &&
  npx eslint .`, `dart analyze`, `go vet ./... && staticcheck ./...`, `cargo clippy`

A checker that is not on PATH is a candidate only when the repo's own manifest declares it
(`[tool.ruff]` in pyproject, `eslint` in devDependencies, `analysis_options.yaml`); then
invoke it through the manifest's runner (`uvx ruff check .`, `npx eslint .`, `dart analyze`).
A tool neither installed nor declared is not a candidate.

**Reject** any candidate that runs a test suite (`pytest`, `jest`, `vitest`, `go test`,
`cargo test`, `flutter test`, `npm test`) — the whole point of the fast gate is that it is not
the suite. If the user passed a command as the argument, use that instead of detecting.

**A gate is a static check** — the repo's own build or analyzer (tsc, go vet, cargo check,
dart analyze), a lint, a type-check, a format-check, a secret scan. Running the program
(`python main.py`, `node app.js`, `go run`, `npm start`, `npm run dev`) is never a gate,
whatever a README or AGENTS.md says about running it before commits. If the only thing a repo
can run is itself, the row is `none`. An interpreter's byte-compiler (`python -m compileall`,
`py_compile`) is not a candidate: it is always present, checks only syntax, and writes cache
files. No configured checker means `none`.

Run the chosen candidate **once**, wrapped in a timer (`Measure-Command` in PowerShell,
`time` in bash), and record the wall-clock seconds. If it exceeds **60 s**, it is not a fast
gate: say so, report the number, and stop — do not write a CLAUDE.md that names a slow gate.
If it fails on the untouched tree, record that too: a red baseline is a fact the first
builder needs, not a reason to hide the command.

**If no candidate exists** — no package scripts, no linter, no compiler, no analyzer (a docs,
notes or tools repo) — write the gate row's Command cell as bare text, no backticks:
`none — <what you checked>, <date>`. Never invent one. A `none` row is complete: builders
write `BASELINE: SKIPPED (no gate in CLAUDE.md)` and delegation proceeds; only a *missing*
row blocks it.

## 2. Write CLAUDE.md from the global template

The template is at `~/.claude/kit/project-template.md` (the installer put it there). If
`./CLAUDE.md` does not exist, run exactly
`cp -n ~/.claude/kit/project-template.md ./CLAUDE.md` as its own command — nothing appended,
because `Read` on that path needs a permission grant and a chained read of the new file is
denied by md-guard before the file exists. `-n` never overwrites. Then fill it in with
`Edit`; when the repo has an `AGENTS.md`, the first Edit is the `@AGENTS.md` line at the top
(rule below). If a CLAUDE.md already exists, **do not overwrite it**: append the template's
`## Commands` section only if the file has no `FAST GATE` row, and leave every other line
alone.

Then, if the file was just created by the copy (or its four detected sections still show
template placeholders), run exactly
`python ~/.claude/kit/scan_project.py --apply .` — it fills **Security
surfaces**, **Layout**, **Conventions** and **Danger list** from what the tree actually
contains, with evidence per line, and leaves any section a human already edited. Never write
those sections yourself; if the script fails, say so and leave the placeholders.

**A repo that has an `AGENTS.md` and no `CLAUDE.md` is the one case where writing the
template takes something away.** Claude Code v2.1.277+ reads `AGENTS.md` as the project
instructions only while no `CLAUDE.md`, `.claude/CLAUDE.md` or `CLAUDE.local.md` sits in the
working directory or above it — so the file you are about to write switches it off, silently.
When the repo has an `AGENTS.md`, make `@AGENTS.md` the first line of the `CLAUDE.md` you
write and put the template below it; that import is the documented way to keep both. The
user's `~/.claude/CLAUDE.md` does not count for that check and keeps loading either way.

Fill in, from what you measured:
- the **FAST GATE** row: the exact command and the measured seconds
- the **Full test suite (I run this)** row, if you found one — and its command goes under
  **Agents never run these** too
- `<PROJECT NAME>` → the repo folder name

**Those three edits plus the scan, and nothing else.** Two runs on identical repos must
produce identical files; a line you add from a README or an AGENTS.md is variance, not setup.

The four detected sections are a floor: the global security-surface list still applies, and
the user may add lines later. Do not add lines of your own.

## 3. Audit, then report

Run `python ~/.claude/kit/audit_project.py .` and paste its last line. It checks that the
gate row is present and either timed or `none`, that nothing in this project duplicates a
global rule, and that no local setting overrides the global output style or re-defines a
user-scope MCP server.

Report, in prose: the gate you chose and why, its measured time, whether the baseline was
green, what the audit said, and the four sections the scan filled, with how many lines each.
Then stop.
