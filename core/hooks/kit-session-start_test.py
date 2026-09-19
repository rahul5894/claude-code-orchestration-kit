"""Self-contained check for kit-session-start.py. Run from anywhere.
Builds its own fixtures in a temp dir: a project with a FAST GATE row, one without, one with
no CLAUDE.md at all. Feeds the hook both ways it is invoked - stdin JSON as Claude Code does,
and `--check <dir>` as verify_live.py does."""
import json
import os
import subprocess
import sys
import tempfile

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit-session-start.py")

tmp = tempfile.mkdtemp(prefix="kit-start-")
WITH = os.path.join(tmp, "with")
WITHOUT = os.path.join(tmp, "without")
NONE = os.path.join(tmp, "none")
for d in (WITH, WITHOUT, NONE):
    os.makedirs(d)
with open(os.path.join(WITH, "CLAUDE.md"), "w", encoding="utf-8") as f:
    f.write("# x\n| **FAST GATE — agents run this** | `make lint` | 4 s |\n")
with open(os.path.join(WITHOUT, "CLAUDE.md"), "w", encoding="utf-8") as f:
    f.write("# x\n## Commands\nnothing named here\n")
# A gated project under a non-ASCII path. Before 2026-09-19 the hook read stdin with the
# locale codec, so this cwd decoded into a path that does not exist and the notice fired on
# a project that is in fact set up.
ACCENT = os.path.join(tmp, "Grüße")
os.makedirs(ACCENT)
with open(os.path.join(ACCENT, "CLAUDE.md"), "w", encoding="utf-8") as f:
    f.write("# x\n| **FAST GATE — agents run this** | `make lint` | 4 s |\n")

CASES = [
    # (want, how, root)
    ("QUIET",  "stdin", ACCENT),
    ("QUIET",  "stdin", WITH),
    ("NOTICE", "stdin", WITHOUT),
    ("NOTICE", "stdin", NONE),
    ("QUIET",  "check", WITH),
    ("NOTICE", "check", WITHOUT),
    ("NOTICE", "check", NONE),
    # Malformed stdin must not crash and must not spam: fail open means silence.
    ("QUIET",  "garbage", WITH),
]


def run(how, root):
    if how == "stdin":
        # Raw UTF-8 bytes, the way JSON.stringify feeds the real hook. text=True would
        # encode with the locale codec and the non-ASCII case could never run.
        raw = json.dumps({"cwd": root}, ensure_ascii=False).encode("utf-8")
        p = subprocess.run([sys.executable, HOOK], input=raw, capture_output=True, cwd=root)
    elif how == "check":
        p = subprocess.run([sys.executable, HOOK, "--check", root], capture_output=True)
    else:
        p = subprocess.run([sys.executable, HOOK], input=b"{not json",
                           capture_output=True, cwd=root)
    return "NOTICE" if b"FAST GATE" in p.stdout else "QUIET"


fails = 0
for want, how, root in CASES:
    got = run(how, root)
    if got != want:
        fails += 1
    print(f"{'ok ' if got == want else 'BAD'} want={want:6} got={got:6} {how:8} {os.path.basename(root)}")
print(f"\n{len(CASES) - fails}/{len(CASES)} passed")
sys.exit(1 if fails else 0)
