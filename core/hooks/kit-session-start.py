"""SessionStart notice: a project with no FAST GATE row gets one line of context, nothing else.

Claude Code feeds SessionStart hooks a JSON object on stdin (`cwd`, `source`, ...) and treats
raw stdout as additional context for the session. This hook prints ONE line when the current
project's CLAUDE.md has no `FAST GATE` row, and prints nothing otherwise. It never writes a
file: creating files in someone's repository on session open is the wrong shape, and the gate
has to be MEASURED, which only `/kit-init` does.

Why it exists: without a named gate, an agent invents one and picks the slowest command it
can find - measured once at two full pytest runs of 159 s each, for a project whose real fast
gate took 7.7 s.

Exit 0 always. Any crash = silence (fail open, dev tool).
    python kit-session-start.py --check <dir>     # same decision, for tests and verification
"""
import json
import os
import re
import sys

GATE_RE = re.compile(r"FAST GATE", re.IGNORECASE)
NOTICE = ("orchestration-kit: this project has no FAST GATE row in CLAUDE.md. "
          "Run /kit-init before delegating anything - it detects the gate, times it, and "
          "writes the file. Until then, do not spawn a builder here.")


def needs_init(root):
    path = os.path.join(root, "CLAUDE.md")
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return not any(GATE_RE.search(line) for line in f)
    except OSError:
        return True


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--check":
        root = sys.argv[2]
    else:
        try:
            data = json.load(sys.stdin)
        except Exception:
            data = {}
        root = data.get("cwd") or os.getcwd()
    if needs_init(root):
        sys.stdout.write(NOTICE)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
