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

**Reject** any candidate that runs a test suite (`pytest`, `jest`, `vitest`, `go test`,
`cargo test`, `flutter test`, `npm test`) — the whole point of the fast gate is that it is not
the suite. If the user passed a command as the argument, use that instead of detecting.

Run the chosen candidate **once**, wrapped in a timer (`Measure-Command` in PowerShell,
`time` in bash), and record the wall-clock seconds. If it exceeds **60 s**, it is not a fast
gate: say so, report the number, and stop — do not write a CLAUDE.md that names a slow gate.
If it fails on the untouched tree, record that too: a red baseline is a fact the first
builder needs, not a reason to hide the command.

## 2. Write CLAUDE.md from the global template

The template is at `~/.claude/kit/project-template.md` (the installer put it there). Copy it
to `./CLAUDE.md` if none exists. If one already exists, **do not overwrite it**: append the
template's `## Commands` section only if the file has no `FAST GATE` row, and leave every
other existing line alone.

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

Leave **Security surfaces in THIS repo**, **Layout** and **Danger list** as the template's
visible placeholders. They are the user's to fill; a guessed security surface is worse than an
empty one because a reviewer would trust it.

## 3. Audit, then report

Run `python ~/.claude/kit/audit_project.py .` and paste its last line. It checks that the
gate row is present and timed, that nothing in this project duplicates a global rule, and that
no local setting overrides the global output style or re-defines a user-scope MCP server.

Report, in prose: the gate you chose and why, its measured time, whether the baseline was
green, what the audit said, and the three placeholders left for the user. Then stop.
