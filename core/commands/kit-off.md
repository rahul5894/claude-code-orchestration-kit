---
description: Turn the orchestration kit OFF in this project - hooks silent, the kit's rules gone from every new chat. Task files stay. Off is every project's default; /kit-on brings it back.
allowed-tools: Bash
---

Run exactly `python ~/.claude/kit/kit_switch.py off "<root>"` and paste its output line.

`<root>` is the absolute **primary working directory** from your environment - the dir
Claude Code was launched in, where the hooks look for the switch. Never `.`: the shell may
have `cd`'d elsewhere, and the Bash tool does not set CLAUDE_PROJECT_DIR (measured 2026-09-23).

It deletes `.claude/rules/orchestration-kit.md` - the kit's rules copy, which is also the switch
every kit hook looks for - and resets a kit output style (`kit-lean` or `orchestrator`) in force
here to `default`. Your own `~/.claude/CLAUDE.md`, this project's `CLAUDE.md` and
`.claude/scratch/` stay. md-guard still stops a read-only agent's writes. Nothing is deleted
but the kit's own copy; `/kit-uninstall` is the one that deletes task files.

If it exits non-zero, show its message and stop: it changed nothing.
Then, from this message on, do not follow the kit's rules (the `orchestration-kit` block in your
context) in this chat. Tell the user: the kit is off - the hooks are silent from their next
event, and the rules leave with the next new chat (`/clear`). No restart needed.
