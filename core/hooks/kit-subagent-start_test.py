"""Self-contained check for kit-subagent-start.py. Run from anywhere.
Builds its own fixtures in a temp dir: an INDEX.md with OPEN, DONE and empty-DECISIONS
buckets, a 20,000-char DECISIONS.md, and a project under a non-ASCII path. Feeds the hook both
ways it is invoked - stdin JSON as Claude Code does, and `--check <dir>` as verify_live.py
does. The last case is the output contract: every CONTEXT payload must parse as the documented
SubagentStart JSON."""
import json
import os
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit-subagent-start.py")
MAX_CHARS = 6000

tmp = tempfile.mkdtemp(prefix="kit-substart-")


def project(name, rows, decisions):
    """rows: (slug, status); decisions: {slug: text}. No INDEX.md row list = no scratch dir."""
    root = os.path.join(tmp, name)
    if rows is None:
        os.makedirs(root)
        return root
    scratch = os.path.join(root, ".claude", "scratch")
    os.makedirs(scratch)
    with open(os.path.join(scratch, "INDEX.md"), "w", encoding="utf-8") as f:
        f.write("# Task index\n| slug | status | updated | next action |\n|---|---|---|---|\n")
        for slug, status in rows:
            f.write(f"| {slug} | {status} | 2026-09-20 | next |\n")
    for slug, text in decisions.items():
        os.makedirs(os.path.join(scratch, slug), exist_ok=True)
        with open(os.path.join(scratch, slug, "DECISIONS.md"), "w", encoding="utf-8") as f:
            f.write(text)
    return root


NOSCRATCH = project("bare", None, {})
ONE = project("one", [("alpha", "OPEN")], {"alpha": "1. use X\n"})
EMPTY = project("empty", [("beta", "OPEN")], {"beta": "\n  \n"})
DONE = project("done", [("gamma", "DONE")], {"gamma": "1. use X\n"})
TWO = project("two", [("delta", "OPEN"), ("epsilon", "OPEN")],
              {"delta": "1. use X\n", "epsilon": "1. use Y\n"})
BIG = project("big", [("zeta", "OPEN")], {"zeta": "1. use X " + "y" * 20000})
# A bucket under a non-ASCII path. The other hooks decoded stdin with the locale codec once and
# the cwd mangled into a path that does not exist, which fails open as silence.
ACCENT = project("Grüße", [("eta", "OPEN")], {"eta": "1. use X\n"})
# Review 02 items 7, 8, 15. A slug is a path COMPONENT: `..` and an absolute path both resolve
# to a real DECISIONS.md outside the bucket, and both must be skipped. A bold slug and a
# `OPEN (blocked)` status are prose an INDEX.md really contains; neither may silence the hook.
DOTDOT = project("dotdot", [("..", "OPEN")], {"..": "1. escaped the bucket\n"})
ABS = project("abs", [(os.path.join(tmp, "one", ".claude", "scratch", "alpha"), "OPEN")], {})
BOLD = project("bold", [("**kit-x**", "OPEN")], {"kit-x": "1. use X\n"})
BLOCKED = project("blocked", [("kappa", "OPEN (blocked)")], {"kappa": "1. use X\n"})
# A bare BLOCKED status is a bucket kit-session-start lists; both hooks agree on what is open.
BLOCKEDBARE = project("blockedbare", [("lambda", "BLOCKED")], {"lambda": "1. use X\n"})
BIGTWO = project("bigtwo",[("theta", "OPEN"), ("iota", "OPEN")],
                 {"theta": "1. use X " + "y" * 20000, "iota": "1. use Y\n"})

CASES = [
    # (want, how, root, substrings the injected text must contain)
    ("QUIET",   "stdin", NOSCRATCH, []),
    ("CONTEXT", "stdin", ONE, ["alpha", "use X"]),
    ("CONTEXT", "check", ONE, ["alpha", "use X"]),
    ("QUIET",   "stdin", EMPTY, []),
    ("QUIET",   "stdin", DONE, []),
    ("CONTEXT", "stdin", TWO, ["delta", "epsilon"]),
    ("CONTEXT", "check", BIG, ["truncated"]),
    # Malformed stdin must not crash and must not spam: fail open means silence.
    ("QUIET",   "garbage", ONE, []),
    ("CONTEXT", "stdin", ACCENT, ["eta", "use X"]),
    ("QUIET",   "stdin", DOTDOT, []),
    ("QUIET",   "stdin", ABS, []),
    ("CONTEXT", "stdin", BOLD, ["kit-x", "use X"]),
    ("CONTEXT", "stdin", BLOCKED, ["kappa", "use X"]),
    ("CONTEXT", "check", BIGTWO, ["Files:", ".claude/scratch/theta/DECISIONS.md",
                                  ".claude/scratch/iota/DECISIONS.md", "truncated"]),
    # Payload cwd follows the shell's `cd`; CLAUDE_PROJECT_DIR (the launch root) wins.
    ("CONTEXT", "envdir", ONE, ["alpha", "use X"]),
    ("CONTEXT", "stdin", BLOCKEDBARE, ["lambda", "use X"]),
    # Launched in a parent dir, then cd into the repo: the launch root has no scratch, cwd does.
    ("CONTEXT", "fallback", ONE, ["alpha", "use X"]),
]

contract_bad = []


def run(how, root):
    # The hook prefers CLAUDE_PROJECT_DIR and a caller inside Claude Code has it set, so every
    # run starts without it; only `envdir` puts it back, pointing at `root`.
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    if how == "stdin":
        # Raw UTF-8 bytes, the way JSON.stringify feeds the real hook. text=True would encode
        # with the locale codec and the non-ASCII case could never run.
        raw = json.dumps({"cwd": root, "agent_type": "builder"}, ensure_ascii=False).encode("utf-8")
        p = subprocess.run([sys.executable, HOOK], input=raw, capture_output=True, cwd=root, env=env)
    elif how == "envdir":
        env["CLAUDE_PROJECT_DIR"] = root.replace(os.sep, "/")
        raw = json.dumps({"cwd": NOSCRATCH, "agent_type": "builder"}, ensure_ascii=False).encode("utf-8")
        p = subprocess.run([sys.executable, HOOK], input=raw, capture_output=True, cwd=NOSCRATCH, env=env)
    elif how == "fallback":
        env["CLAUDE_PROJECT_DIR"] = NOSCRATCH.replace(os.sep, "/")
        raw = json.dumps({"cwd": root, "agent_type": "builder"}, ensure_ascii=False).encode("utf-8")
        p = subprocess.run([sys.executable, HOOK], input=raw, capture_output=True, cwd=root, env=env)
    elif how == "check":
        p = subprocess.run([sys.executable, HOOK, "--check", root], capture_output=True, env=env)
    else:
        p = subprocess.run([sys.executable, HOOK], input=b"{not json",
                           capture_output=True, cwd=root, env=env)
    out = p.stdout.decode("utf-8", "replace").strip()
    if not out:
        return "QUIET", ""
    try:
        got = json.loads(out)["hookSpecificOutput"]
        assert got["hookEventName"] == "SubagentStart"
        text = got["additionalContext"]
        assert len(text) <= MAX_CHARS, f"{len(text)} chars"
    except (ValueError, KeyError, AssertionError) as e:
        contract_bad.append(f"{os.path.basename(root)}: {type(e).__name__}: {e}")
        return "CONTEXT", ""
    return "CONTEXT", text


fails = 0
for want, how, root, needles in CASES:
    got, text = run(how, root)
    missing = [n for n in needles if n not in text]
    bad = got != want or missing
    if bad:
        fails += 1
    print(f"{'BAD' if bad else 'ok '} want={want:7} got={got:7} {how:8} "
          f"{os.path.basename(root)}{' missing ' + str(missing) if missing else ''}")
if contract_bad:
    fails += 1
print(f"{'BAD' if contract_bad else 'ok '} every CONTEXT payload is SubagentStart JSON "
      f"under {MAX_CHARS} chars {contract_bad if contract_bad else ''}")
total = len(CASES) + 1
print(f"\n{total - fails}/{total} passed")
sys.exit(1 if fails else 0)
