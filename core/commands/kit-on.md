---
description: Turn the orchestration kit ON in this project - it is off in every project until then. Copies the kit's rules in; hooks run from their next event; the default output style stays (never kit-lean or orchestrator); asks once whether the project should also keep project-records.
allowed-tools: Bash, Read, AskUserQuestion
---

Run exactly `python ~/.claude/kit/kit_switch.py on "<root>"` and paste its output.
`<root>` = the absolute launch dir (your primary working directory), never `.`.

It copies the kit's rules to `.claude/rules/orchestration-kit.md` - Claude Code loads them from
there in every new chat and in every subagent, and every kit hook looks for that file first -
lists it in `.git/info/exclude` so it is never committed, and keeps the default output style
(a kit style, `kit-lean` or `orchestrator`, in force here is overridden with `default`). A plugin
that keeps a session journal of its own (remember) is switched off here, in
`.claude/settings.local.json`, from the next session: the kit's task timeline keeps that record,
and `/kit-off` turns the plugin back on.
If it exits non-zero, show its message and stop.

Then, so the kit works in THIS chat too, Read `~/.claude/kit/orchestration-kit.md` whole and
follow it from now on. Tell the user: the kit is on - the hooks from their next event, the rules
now and in every new chat; `/clear` shows this project's task list; `/kit-init` if this project
has no `CLAUDE.md` with a FAST GATE row.

## Records: one question

The project-records skill keeps a project's permanent record in its docs/ folder, committed to
git: client mails and calls filed by date, every decision quoted with who and when, questions,
findings and numbered work items, each with an id. The kit keeps the working memory of a task;
the two divide the work, one home per fact. Ask only when both hold: this project does not keep
it yet (no docs/TIMELINE.md beside `.claude/skills/project-records/`), and this machine has it
(`~/.claude/commands/records-install.md` exists). Otherwise say nothing about it.

One AskUserQuestion, the recommended option first with `(Recommended)` in its label:
- recommend **No** when the project already runs its own record or next-item system - its
  `CLAUDE.md` has standing orders for filing client documents or a history, it has a next-item
  skill or its own findings file - or it is not client work: nothing changes;
- recommend **Yes** for client work with no such system: tell the user to type
  `/records-install` - a typed command that copies the skill in and starts its setup interview.
  Never run it, and never copy the skill in yourself.

No AskUserQuestion tool (a headless run): write the question with its two options and stop.
