---
description: Turn the orchestration kit OFF in this project only - hooks silent, kit rules not loaded, default output style. Files stay. /kit-on undoes it.
allowed-tools: Bash
---

Run exactly `python ~/.claude/kit/kit_switch.py off "<root>"` and paste its output line.

`<root>` is the absolute **primary working directory** from your environment - the dir
Claude Code was launched in, where the hooks look for the marker. Never `.`: the shell may
have `cd`'d elsewhere, and the Bash tool does not set CLAUDE_PROJECT_DIR (measured 2026-09-23).

It writes `.claude/kit-off` (every kit hook exits silently while it exists) and adds two keys to
`.claude/settings.local.json`: `claudeMdExcludes` for the kit's rules file, and `outputStyle`
`default` unless the project already uses a style of its own. Your own `~/.claude/CLAUDE.md` and
this project's `CLAUDE.md` keep loading. md-guard still stops a read-only agent's writes.
`.claude/kit-off` is a plain file: in a shared repo, gitignore it, or commit it on purpose to
turn the kit off in every clone. Nothing is deleted; `/kit-uninstall` is the one that
deletes.

If it exits non-zero, show its message and stop: it changed nothing.
Then tell the user: restart Claude Code in this project for the rules and style to drop.
