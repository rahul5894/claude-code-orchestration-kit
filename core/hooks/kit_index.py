"""The open rows of a task-bucket index, `.claude/scratch/INDEX.md`, for the two hooks that read
it (kit-session-start lists them and hands over STATE.md; kit-subagent-start injects DECISIONS.md),
so both agree on what is open.

Two shapes are read, because models write both: the /task table (`| slug | status | updated |
next action |`) and a bullet list (`- slug — STATUS — next`). Measured 2026-09-29: Strem-setup's
INDEX is bullets, and the table-only reader saw none of its 3 open buckets. OPEN and BLOCKED rows
of the table count as before. Any other open-sounding status (`IN PROGRESS` was skipped) and any
bullet row count only when the bucket folder exists: a legend table (`| OPEN | active |`) or a
prose bullet must not become a bucket. Callers still validate the slug before any path."""
import os
import re

CELL_RE = re.compile(r"(?<!\\)\|")
BULLET_RE = re.compile(r"[-*]\s+(\S+?)\s+[—–-]{1,2}\s+(.+?)(?:\s+[—–-]{1,2}\s+(.*))?")
OPEN = ("OPEN", "BLOCKED")
OPEN_IF_FOLDER = ("IN PROGRESS", "IN-PROGRESS", "WIP", "ACTIVE", "ONGOING", "PAUSED", "WAITING",
                  "PENDING", "STARTED", "TODO")


def open_rows(index_path):
    """(slug, status, next action) for every open row, in file order. Unreadable = []."""
    scratch = os.path.dirname(index_path)
    try:
        with open(index_path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        s = line.strip()
        table = s.startswith("|")
        if table:
            cells = [c.strip() for c in CELL_RE.split(s.strip("|"))]
            if len(cells) < 2:
                continue
            slug, status, nxt = cells[0], cells[1], cells[3] if len(cells) >= 4 else ""
        else:
            m = BULLET_RE.fullmatch(s)
            if not m:
                continue
            slug, status, nxt = m.group(1), m.group(2), m.group(3) or ""
        slug = slug.strip("*` ")
        word = status.strip("*` ").upper()
        if not slug or not word.startswith(OPEN + OPEN_IF_FOLDER):
            continue
        if (not table or not word.startswith(OPEN)) and not os.path.isdir(os.path.join(scratch, slug)):
            continue
        out.append((slug, status.strip(), nxt.strip()))
    return out
