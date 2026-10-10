---
description: Turn the orchestration kit ON in this project - it is off in every project until then. Copies the kit's rules in; hooks run from their next event; the default output style stays (never kit-lean or orchestrator).
allowed-tools: Bash, Read
---

Run exactly `python ~/.claude/kit/kit_switch.py on "<root>"` and paste its output line.
`<root>` = the absolute launch dir (your primary working directory), never `.`.

It copies the kit's rules to `.claude/rules/orchestration-kit.md` - Claude Code loads them from
there in every new chat and in every subagent, and every kit hook looks for that file first -
lists it in `.git/info/exclude` so it is never committed, and keeps the default output style
(a kit style, `kit-lean` or `orchestrator`, in force here is overridden with `default`).
If it exits non-zero, show its message and stop.

Then, so the kit works in THIS chat too, Read `~/.claude/kit/orchestration-kit.md` whole and
follow it from now on. Tell the user: the kit is on - the hooks from their next event, the rules
now and in every new chat; `/clear` shows this project's task list; `/kit-init` if this project
has no `CLAUDE.md` with a FAST GATE row.
