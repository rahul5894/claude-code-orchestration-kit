---
description: Turn the orchestration kit back ON in this project after /kit-off or /kit-uninstall. Undoes exactly what the off switch recorded.
allowed-tools: Bash
---

Run exactly `python ~/.claude/kit/kit_switch.py on "<root>"` and paste its output line.
`<root>` = the absolute launch dir (your primary working directory), never `.`.

It removes `.claude/kit-off` and takes back only the `settings.local.json` keys the off switch
added, restoring a style it replaced. If it exits non-zero, show its message and stop.
Then tell the user: restart Claude Code here; run `/kit-init` if this project has no `CLAUDE.md`.
