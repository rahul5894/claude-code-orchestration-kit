# Kit commands: quick reference

Type these in the Claude Code chat, inside the project you mean.

## In one project

| Command | What happens | Note |
|---|---|---|
| `/kit-off` | Turns the kit off **in this project only**. Kit hooks go silent and the kit's rules stop loading. Nothing is deleted. | Stays off until you type `/kit-on`. Kit updates (`install.ps1`) do not turn it back on. |
| `/kit-on` | Turns the kit back on in this project. It undoes exactly what `/kit-off` did. | |
| `/kit-uninstall` | Removes the kit from **this project only**. It asks before deleting anything, zips the task notes to `~/.claude/kit-backups/`, can remove the kit-written parts of `CLAUDE.md`, then turns the kit off here for good. | The kit stays installed for every other project. `/kit-on` still brings it back here. |
| `/kit-init` | Sets up a new project: finds and times its fast check, writes `CLAUDE.md`, then audits the project. | Once per project. |
| `/task` | With no words: lists every task and its next step. With a sentence: continues a task or opens a new one. | |
| `/continue` | After `/clear`, picks up the open task from its `STATE.md`. | Two windows: each resumes its own task and skips the one the other window is on. Two or more free tasks and no own one: it asks which. |

**After `/kit-off` or `/kit-on`:** the hooks switch at once, even in the chat you are in. The
rules switch in the **next new chat** in that project. The chat that was already open keeps the
rules it loaded when it started. There is no need to restart VS Code. If you are not sure a
new chat started, reload the window (`Developer: Reload Window`).

## On the whole machine

Run these in PowerShell, in the kit folder.

| Command | What happens |
|---|---|
| `pwsh -File install.ps1` | Installs or updates the kit in `~/.claude` for every project. Safe to run again. Restart Claude Code after: agents and output styles load at startup. |
| `pwsh -File uninstall.ps1 -WhatIf` | Shows what uninstall would remove. Changes nothing. |
| `pwsh -File uninstall.ps1` | Removes the kit from `~/.claude` for every project. Your own files and settings stay, and it writes backups. Projects are not touched: a project's `.claude/kit-off` or task notes stay where they are. `install.ps1` brings the kit back. |

## Good to know

- **Off follows the folder you open.** The switch is the file `<project>/.claude/kit-off`, looked
  up in the folder Claude Code started in. Open the project from that same folder.
- **In a shared git repo**, `.claude/kit-off` shows up in `git status`. Add it to `.gitignore`,
  or commit it on purpose to turn the kit off for everyone.
- **One guard stays on even when the kit is off:** the review agents (refuter, debugger) still
  cannot write files. It is a safety rule, and it only matters if you ask for one of them.
- **Output style is `default` on this machine** (`"outputStyle": "default"` in
  `~/.claude/settings.json`), so Claude makes changes itself and spawns an agent only when you
  ask. The kit sets no style of its own.
