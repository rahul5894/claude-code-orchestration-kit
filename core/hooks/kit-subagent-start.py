"""SubagentStart injector: a spawned agent gets the DECISIONS.md of every open bucket (kit_index.py).

Claude Code feeds SubagentStart hooks a JSON object on stdin (`cwd`, `agent_type`, ...) and
adds `hookSpecificOutput.additionalContext` to the new agent's context. A decision recorded in
a bucket only binds an agent that has read it, and an agent that inherits no conversation
cannot know a bucket exists - so the decisions arrive at spawn instead of being asked for.

Only OPEN and BLOCKED buckets (the status column of `.claude/scratch/INDEX.md`) are injected, and only
their DECISIONS.md: the agent files carry their own reminders. Capped at 6000 characters -
hooks.md allows 10,000, and a spawn pays this on every agent.

In a project-records project (kit_index.records_project: docs/ is the record, bucket
kit-records-integration D001) the agent also gets the rule that docs/ is the one home, and the
docs/DECISIONS.md heading of every D-NNN the open buckets' DECISIONS.md and STATE.md cite - so a
bucket cites a project decision by its id and never has to restate it for its agents to see it
(measured 2026-10-11: a bucket restated a docs decision's whole build plan for exactly that).

Exit 0 always. Any crash = silence (fail open, dev tool). Never writes a file.
    python kit-subagent-start.py --check <dir>     # same decision, for tests and verification
"""
import os
import sys

# The hook's own folder, explicitly: under PYTHONSAFEPATH=1 (or python -P / -I) the script dir
# is not on sys.path, the import fails and the hook exits 1 - which fails open (refuter-02).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_off import kit_off  # noqa: E402

# --check <dir>: the read-only mode tests and verify_live use - on or off.
READONLY = len(sys.argv) >= 3 and sys.argv[1] == "--check"
if __name__ == "__main__" and not READONLY and kit_off():
    sys.exit(0)  # off here, the default: out before the imports below (kit-default-off-optimize D003)

import json  # noqa: E402
import re  # noqa: E402

from kit_index import open_rows, record_heads, records_project  # noqa: E402

MAX_CHARS = 6000
LEAD = ("orchestration-kit: decisions already made for the open bucket(s) below. A change "
        "that would reverse one means stop and report; never re-decide.")
RECORDS_LEAD = ("project-records: docs/ is this project's record; a bucket is working notes. An "
                "entry already in docs/ (D-/F-/L-/Q-/B-NNN) is cited by its id, never restated; a new "
                "decision, finding or lesson goes in your report for the main session to file there. "
                "A docs decision binds like a bucket one: reversing it means stop and report.")
RECORDS_HEADS = ("Project decisions the open bucket(s) cite, as docs/DECISIONS.md heads them (the whole "
                 "entry: node scripts/trace.mjs <id>):")
CUT = "\n... (truncated {} chars: read the files above for the rest)"
# A slug is one path component, not a path (DECISIONS 10).
SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def open_slugs(index_path):
    """Slugs of the open rows kit-session-start lists (kit_index.open_rows: table or bullets, any
    status that is not a closed one). A slug written `**bold**` or in backticks still resolves -
    an INDEX.md is prose, and a formatting flourish must not silently disable the injector."""
    return [slug for slug, _, _ in open_rows(index_path)]


def notes(scratch, name):
    """(slug, text) of note `name` in every open bucket that has one, in INDEX order."""
    out = []
    root = os.path.realpath(scratch) + os.sep
    for slug in open_slugs(os.path.join(scratch, "INDEX.md")):
        # `..` or an absolute path in the slug column would read a file the bucket does not
        # own; the resolved path has to stay under .claude/scratch/.
        if slug in (".", "..") or not SLUG_RE.fullmatch(slug):
            continue
        path = os.path.join(scratch, slug, name)
        if not os.path.realpath(path).startswith(root):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                out.append((slug, f.read()))
        except OSError:
            continue
    return out


def sections(scratch):
    """(relative path, section) per open bucket whose DECISIONS.md has content."""
    out = []
    for slug, body in notes(scratch, "DECISIONS.md"):
        if not body.strip():
            continue
        rel = f".claude/scratch/{slug}/DECISIONS.md"
        out.append((rel, f"## Bucket {slug} — {rel}\n\n{body}"))
    return out


def main():
    if READONLY:
        root = sys.argv[2]
    else:
        try:
            # Explicit UTF-8, same as the other hooks: sys.stdin uses the locale codec
            # (cp1252 on Windows) while the payload leaves non-ASCII raw, so a cwd with an
            # accent decodes into a path that does not exist and nothing is injected.
            data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        except Exception:
            data = {}
        # The first of CLAUDE_PROJECT_DIR (the launch root; payload cwd follows the shell's
        # `cd`) and payload cwd (a session launched in a parent dir) that has a scratch dir
        # (D011). No fallback to os.getcwd(): injecting another repo's decisions is worse than
        # injecting none.
        root = next((r for r in (os.environ.get("CLAUDE_PROJECT_DIR"), data.get("cwd"))
                     if r and os.path.isdir(os.path.join(r, ".claude", "scratch"))), None)
        if not root or kit_off(root):
            return
    scratch = os.path.join(root, ".claude", "scratch")
    if not os.path.isfile(os.path.join(scratch, "INDEX.md")):
        return
    found = sections(scratch)
    records = records_project(root)
    if not found and not records:
        return
    # The file list and the records rule go first, before anything that can be cut: a truncated
    # payload still names every bucket it was carrying and where the project's record is. The
    # docs headings go last - the first thing cut, and `trace` gives any of them back.
    parts = [LEAD + "\nFiles: " + ", ".join(rel for rel, _ in found)] if found else []
    if records:
        parts.append(RECORDS_LEAD)
    parts += [body for _, body in found]
    if records:
        heads = record_heads(root, [t for _, t in notes(scratch, "DECISIONS.md") + notes(scratch, "STATE.md")])
        if heads:
            parts.append(RECORDS_HEADS + "\n" + "\n".join(heads))
    text = "\n\n".join(parts)
    if len(text) > MAX_CHARS:
        cut = CUT.format(len(text) - MAX_CHARS)
        cut = CUT.format(len(text) - MAX_CHARS + len(cut))  # the marker costs budget too
        text = text[:MAX_CHARS - len(cut)] + cut
    sys.stdout.write(json.dumps({"hookSpecificOutput": {
        "hookEventName": "SubagentStart",
        "additionalContext": text,
    }}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
