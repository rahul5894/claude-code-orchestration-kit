# Kit commands: quick reference

Type these in the Claude Code chat, inside the project you mean.

## In one project

| Command | What happens | Note |
|---|---|---|
| `/kit-on` | Turns the kit on **in this project**. The kit is **off in every project** until you do: it copies the kit's rules into `.claude/rules/orchestration-kit.md`, and that file is also the switch. | Stays on until `/kit-off`. Kit updates (`install.ps1`) keep the copy current. |
| `/kit-off` | Turns the kit off in this project: deletes that copy. Kit hooks go silent and the kit's rules stop loading. Task notes stay. | Stays off until `/kit-on`. |
| `/kit-uninstall` | Removes the kit from **this project only**. It asks before deleting anything, zips the task notes to `~/.claude/kit-backups/`, can remove the kit-written parts of `CLAUDE.md`, then turns the kit off here. | The kit stays installed for every other project. `/kit-on` still brings it back here. |
| `/kit-init` | Sets up a new project: turns the kit on, finds and times its fast check, writes `CLAUDE.md`, then audits the project. | Once per project. |
| `/task` | With no words: lists every task and its next step. With a sentence: continues a task or opens a new one. | |
| `/continue` | After `/clear`, picks up the open task from its `STATE.md`, its `SESSIONS.md` timeline and the last session's verbatim record; an earlier session is opened only when something is unclear. | Two windows: each resumes its own task and skips the one the other window is on. Two or more free tasks and no own one: it recommends one, with a reason, and asks. |

**After `/kit-on` or `/kit-off`:** the hooks switch at once, even in the chat you are in, and in
that chat Claude starts (or stops) following the kit's rules right away. Every **new chat**
(`/clear`, a new window) loads them, or not, by itself. There is no need to restart VS Code.

## On the whole machine

Run these in PowerShell, in the kit folder.

| Command | What happens |
|---|---|
| `pwsh -File install.ps1` | Installs or updates the kit in `~/.claude` for every project. Safe to run again. Restart Claude Code after: agents and output styles load at startup. |
| `pwsh -File uninstall.ps1 -WhatIf` | Shows what uninstall would remove. Changes nothing. |
| `pwsh -File uninstall.ps1` | Removes the kit from `~/.claude` for every project. Your own files and settings stay, and it writes backups. Projects are not touched: a project's task notes, and the rules copy where the kit was on, stay where they are - `/kit-off` there first. `install.ps1` brings the kit back. |

## Good to know

- **On follows the folder you open.** The switch is the file
  `<project>/.claude/rules/orchestration-kit.md`, looked up in the folder Claude Code started in.
  Open the project from that same folder.
- **Never committed:** `/kit-on` lists the file in the repo's own `.git/info/exclude`, so
  `git status` does not show it. It is this machine's copy (the kit keeps it current), so do not
  commit it; turn the kit on in each clone instead.
- **Off costs nothing:** in a project with the kit off, each kit hook exits right after Python
  starts (~25 ms), and the kit's rules take no room in the chat.
- **One guard stays on even when the kit is off:** the review agents (refuter, debugger) still
  cannot write files. It is a safety rule, and it only matters if you ask for one of them.
- **Output style is `default` on this machine** (`"outputStyle": "default"` in
  `~/.claude/settings.json`), so Claude makes changes itself and spawns an agent only when you
  ask. The kit sets no style of its own.
