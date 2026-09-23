---
description: Remove the orchestration kit from THIS project - task buckets, the kit-written CLAUDE.md - then switch the kit off here for good. Asks before deleting anything. The global kit stays (uninstall.ps1 removes that).
allowed-tools: Bash, Read, Edit
---

Remove the kit from this project only. **Nothing is deleted before the user answers step 2.**

`<root>` below is the project: the absolute primary working directory Claude Code was launched
in. Start every shell command with `cd "<root>" &&` - the shell may have moved.

## 1. Look, change nothing

- `.claude/scratch/`: count the bucket folders (every folder but `_inbox`), the ones under
  `_closed/`, and the OPEN or BLOCKED rows of `.claude/scratch/INDEX.md`.
- `CLAUDE.md`: compare it with `~/.claude/kit/project-template.md`
  (`git diff --no-index --stat ~/.claude/kit/project-template.md CLAUDE.md`). List the `##`
  headings both files share: those sections came from `/kit-init`. List every other heading as
  the user's own.
- `git status --short .claude CLAUDE.md`: say which of these are committed.

## 2. Ask once, with the numbers

One question per item, showing the counts and headings from step 1:

- Buckets: **zip, then delete** (recommended) / delete without a backup / keep.
- CLAUDE.md: **keep** (recommended when it has headings of the user's own) / delete the
  kit-init sections only / delete the file.

Open buckets are unfinished work: say how many before the user picks. No user to answer (a
headless `claude -p` run): stop here and report step 1 - delete nothing.

## 3. Do what was chosen

- Zip, outside the repo so git never sees it, one file per run:
  `python -c "import os,shutil,datetime; d=os.path.expanduser('~/.claude/kit-backups'); os.makedirs(d, exist_ok=True); print(shutil.make_archive(os.path.join(d, os.path.basename(os.getcwd()) + '-scratch-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S')), 'zip', '.claude', 'scratch'))"`
  and paste the path it prints. Only when the zip exists, delete `.claude/scratch/`.
- CLAUDE.md: edit out exactly the sections picked, nothing else.
- Always, last: `python ~/.claude/kit/kit_switch.py off "<root>"`, which writes `.claude/kit-off`, so
  the kit's hooks, rules and style never run here again. If it exits non-zero, show its message
  and stop.

## 4. Report

What was deleted, where the backup is, what was kept. Then:
- restart Claude Code in this project;
- `/kit-on` brings the kit back here;
- to remove the kit from the whole machine: `pwsh -File uninstall.ps1` in the kit checkout.
