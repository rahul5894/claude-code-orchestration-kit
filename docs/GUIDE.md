# Kit guide — the short version

Plain steps for the orchestration kit. Details live in README.md and SETUP-NEW-MACHINE.md.
Every command on one page: [COMMANDS.md](../COMMANDS.md).

## 1. Install (once per machine, and after every kit update)

```
cd D:\Projects\claude-code-orchestration-kit
pwsh -File install.ps1
```

Then restart Claude Code. The installer copies the agents, commands, hooks and two output
styles into `~/.claude`, and the kit's rules to `~/.claude/kit/orchestration-kit.md`. Your own
`~/.claude/CLAUDE.md` is not touched. **The kit is off in every project until you type `/kit-on`
(or `/kit-init`) there.**

## 2. The two modes

| Mode | What it does | How to switch |
|---|---|---|
| `default` (after install) | Plain Claude Code: Claude writes the code itself, no builder or refuter unless you ask; where the kit is on, its hooks, guards, rules and `/task` + `/continue` still apply | `/output-style default` |
| `kit-lean` | Claude writes the code itself, runs the gate, then `/code-review` (and `/security-review` for risky files) | `/output-style kit-lean` |
| `orchestrator` | Full loop: builder agent writes, refuter + verifier review, Fable/Opus split | `/output-style orchestrator` |

- The kit sets no style, so `default` is on after install; `/kit-init` does not change it. Bench E wave G:
  plain Opus 5.5 xhigh tied `kit-lean` on every hidden test, 7% faster, 17% cheaper.
- `/output-style` changes the mode for THIS project only (it writes `.claude/settings.local.json`).
- `orchestrator` for big or multi-day work; `kit-lean` when you want the review step too.

## 3. A new project

Type `/kit-init` once. It turns the kit on here, finds the project's fast check (the "gate"),
times it and writes the project `CLAUDE.md`. In a project where the kit is on but that row is
missing, a message at session start reminds you.

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

## 6. Kit on and off, one project at a time

- The kit is **off** in every project by default: no hooks at work, no kit rules in the chat.
- `/kit-on` - on here: it copies the kit's rules into `.claude/rules/orchestration-kit.md`
  (kept out of git through `.git/info/exclude`); that file is also the switch.
- `/kit-off` - off here: the copy goes, kit hooks are silent, and a kit output style in force
  here (kit-lean or orchestrator) goes back to default. Task files stay. (md-guard still stops
  the read-only reviewer agents from writing.)
- `/kit-uninstall` - removes the kit's files from this project (asks first, can zip your task
  folders), then turns the kit off here. `/kit-on` still brings it back.
- After any of these, the hooks switch at once, and Claude follows (or stops following) the
  kit's rules in the same chat; every new chat loads them, or not, by itself. No need to
  restart VS Code.

## 7. Remove the kit from the whole machine

Run `/kit-uninstall` (or at least `/kit-off`) first in every project where the kit is on: it is
a kit command, so it is gone after this step, and the rules copy would keep loading there. Then:

```
pwsh -File uninstall.ps1 -WhatIf    # shows every change, writes nothing
pwsh -File uninstall.ps1
```

It removes only the kit's own files, hooks and settings; your own stay, and backups are
written first. Settings the kit changed at install (an effort level, a plugin it turned off)
go back to what your first backup shows you had before the kit.
