---
description: Turn the orchestration kit back ON in this project after /kit-off or /kit-uninstall, on the default output style (never kit-lean or orchestrator).
allowed-tools: Bash
---

Run exactly `python ~/.claude/kit/kit_switch.py on "<root>"` and paste its output line.
`<root>` = the absolute launch dir (your primary working directory), never `.`.

It removes `.claude/kit-off` and takes back only the `settings.local.json` keys the off switch
added. It never brings back a kit style (`kit-lean`, `orchestrator`): the project stays on the
default style, and if one of those would still be in force it writes `outputStyle` `default`.
If it exits non-zero, show its message and stop.
Then tell the user: the hooks are on already and the rules load in the next new chat here; run
`/kit-init` if this project has no `CLAUDE.md`.
