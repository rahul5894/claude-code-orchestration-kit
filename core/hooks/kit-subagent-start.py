"""SubagentStart injector: a spawned agent gets the DECISIONS.md of every OPEN or BLOCKED bucket.

Claude Code feeds SubagentStart hooks a JSON object on stdin (`cwd`, `agent_type`, ...) and
adds `hookSpecificOutput.additionalContext` to the new agent's context. A decision recorded in
a bucket only binds an agent that has read it, and an agent that inherits no conversation
cannot know a bucket exists - so the decisions arrive at spawn instead of being asked for.

Only OPEN and BLOCKED buckets (the status column of `.claude/scratch/INDEX.md`) are injected, and only
their DECISIONS.md: the agent files carry their own reminders. Capped at 6000 characters -
hooks.md allows 10,000, and a spawn pays this on every agent.

Exit 0 always. Any crash = silence (fail open, dev tool). Never writes a file.
    python kit-subagent-start.py --check <dir>     # same decision, for tests and verification
"""
import json
import os
import re
import sys

# The hook's own folder, explicitly: under PYTHONSAFEPATH=1 (or python -P / -I) the script dir
# is not on sys.path, the import fails and the hook exits 1 - which fails open (refuter-02).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_off import kit_off  # noqa: E402

MAX_CHARS = 6000
LEAD = ("orchestration-kit: decisions already made for the open bucket(s) below. A change "
        "that would reverse one means stop and report; never re-decide.")
CUT = "\n... (truncated {} chars: read the files above for the rest)"
# A slug is one path component, not a path (DECISIONS 10).
SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


# A cell boundary is a pipe not escaped as `\|`.
CELL_RE = re.compile(r"(?<!\\)\|")


def open_slugs(index_path):
    """Slugs whose status cell starts with OPEN or BLOCKED (the rows kit-session-start lists).
    The header and `|---|` rows fail the same test. `OPEN (blocked)` counts, and a slug written
    `**bold**` or in backticks still resolves - an INDEX.md is prose, and a formatting flourish
    must not silently disable the injector."""
    out = []
    with open(index_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            cells = [c.strip() for c in CELL_RE.split(line.strip().strip("|"))]
            if len(cells) >= 2 and cells[1].upper().startswith(("OPEN", "BLOCKED")):
                slug = cells[0].strip("*` ")
                if slug:
                    out.append(slug)
    return out


def sections(scratch):
    """(relative path, section) per OPEN or BLOCKED bucket whose DECISIONS.md has content."""
    out = []
    root = os.path.realpath(scratch) + os.sep
    for slug in open_slugs(os.path.join(scratch, "INDEX.md")):
        # `..` or an absolute path in the slug column would read a file the bucket does not
        # own; the resolved path has to stay under .claude/scratch/.
        if slug in (".", "..") or not SLUG_RE.fullmatch(slug):
            continue
        path = os.path.join(scratch, slug, "DECISIONS.md")
        if not os.path.realpath(path).startswith(root):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                body = f.read()
        except OSError:
            continue
        if not body.strip():
            continue
        rel = f".claude/scratch/{slug}/DECISIONS.md"
        out.append((rel, f"## Bucket {slug} — {rel}\n\n{body}"))
    return out


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--check":
        root = sys.argv[2]
    elif kit_off():
        return
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
    if not found:
        return
    # The file list goes in the lead, before anything that can be cut: a truncated payload
    # still names every bucket it was carrying.
    text = (LEAD + "\nFiles: " + ", ".join(rel for rel, _ in found) + "\n\n"
            + "\n\n".join(body for _, body in found))
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
