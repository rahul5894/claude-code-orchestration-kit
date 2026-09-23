# Kit guide — the short version

Plain steps for the orchestration kit. Details live in README.md and SETUP-NEW-MACHINE.md.

## 1. Install (once per machine, and after every kit update)

```
cd D:\Projects\claude-code-orchestration-kit
pwsh -File install.ps1
```

Then restart Claude Code. The installer copies the agents, commands, hooks and two output
styles into `~/.claude`, and writes the kit's rules to `~/.claude/rules/orchestration-kit.md`.
Your own `~/.claude/CLAUDE.md` is not touched.

## 2. The two modes

| Mode | What it does | How to switch |
|---|---|---|
| `kit-lean` (default) | Claude writes the code itself, runs the gate, then `/code-review` (and `/security-review` for risky files) | `/output-style kit-lean` |
| `orchestrator` | Full loop: builder agent writes, refuter + verifier review, Fable/Opus split | `/output-style orchestrator` |

- `kit-lean` is on in every project after install. `/kit-init` does not change it.
- `/output-style` changes the mode for THIS project only (it writes `.claude/settings.local.json`).
- Use `orchestrator` for big or multi-day work; `kit-lean` for everything else.

## 3. A new project

Type `/kit-init` once. It finds the project's fast check (the "gate"), times it and writes
the project `CLAUDE.md`. Until then, a message at session start reminds you.

## 4. Long work that spans sessions

- `/task <one sentence>` opens a task folder (a "bucket") under `.claude/scratch/`.
- `/task` with no words lists every open task.
- Next day, or after `/clear`, type `/continue`.

## 5. Messages you will see

- `Open task(s): <name> - type /continue to resume.` A task is waiting; `/continue` picks it up.
- `Context N% full - handoff written? Next: /clear, then type /continue.`
  The chat is getting long (from about 45%). Claude has written where it stopped. Type
  `/clear`, then `/continue`, and it resumes from that note, fresh and cheaper.
- `this project has no FAST GATE row` - run `/kit-init`.

## 6. Kit off in ONE project

- `/kit-off` - the kit goes quiet here: kit hooks silent, kit rules not loaded, default style.
  Files stay. (md-guard still stops the read-only reviewer agents from writing.)
- `/kit-on` - back on, exactly as before.
- `/kit-uninstall` - removes the kit's files from this project (asks first, can zip your task
  folders), then turns the kit off here for good. `/kit-on` still brings it back.
- Restart Claude Code in that project after any of these.

## 7. Remove the kit from the whole machine

Run `/kit-uninstall` first in any project you want cleaned (it is a kit command, so it is gone
after this step). Then:

```
pwsh -File uninstall.ps1 -WhatIf    # shows every change, writes nothing
pwsh -File uninstall.ps1
```

It removes only the kit's own files, hooks and settings; your own stay, and backups are
written first. Settings the kit changed at install (an effort level, a plugin it turned off)
go back to what your first backup shows you had before the kit.
