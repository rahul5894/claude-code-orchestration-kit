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

# Task buckets: INDEX.md rows OPEN/BLOCKED are listed for the model and named to the user.
def bucket_project(name, gated, rows):
    root = os.path.join(tmp, name)
    os.makedirs(os.path.join(root, ".claude", "scratch"))
    if gated:
        with open(os.path.join(root, "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write("# x\n| **FAST GATE — agents run this** | `make lint` | 4 s |\n")
    with open(os.path.join(root, ".claude", "scratch", "INDEX.md"), "w", encoding="utf-8") as f:
        f.write("# Task index\n| slug | status | updated | next action |\n|---|---|---|---|\n")
        for slug, status, nxt in rows:
            f.write(f"| {slug} | {status} | 2026-09-23 | {nxt} |\n")
    return root


BUCKETS = bucket_project("buckets", True, [("live-one", "OPEN", "run builder-02"),
                                           ("old-one", "DONE", "nothing")])
MANY = bucket_project("many", True, [(f"b{i}", "OPEN", f"step {i}") for i in range(10)])
MIX = bucket_project("mix", True, [("blocked-one", "BLOCKED", "wait for the user"),
                                   ("long-one", "OPEN", "y" * 300),
                                   ("pipe-one", "OPEN", r"a \| b"),
                                   ("../x", "OPEN", "escaped the scratch dir")])


def run(how, root, project_dir=None, source="startup"):
    """Parsed stdout: {} when silent, {"_bad": text} when it is not JSON."""
    # The hook prefers CLAUDE_PROJECT_DIR; a caller inside Claude Code has it set, so every run
    # starts from an env without it and only the case that tests it puts it back.
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    if project_dir:
        env["CLAUDE_PROJECT_DIR"] = project_dir
    if how == "stdin":
        # Raw UTF-8 bytes, the way JSON.stringify feeds the real hook. text=True would
        # encode with the locale codec and the non-ASCII case could never run.
        raw = json.dumps({"cwd": root, "source": source}, ensure_ascii=False).encode("utf-8")
        p = subprocess.run([sys.executable, HOOK], input=raw, capture_output=True, cwd=root, env=env)
    elif how == "check":
        p = subprocess.run([sys.executable, HOOK, "--check", root], capture_output=True, env=env)
    else:
        p = subprocess.run([sys.executable, HOOK], input=b"{not json",
                           capture_output=True, cwd=root, env=env)
    out = p.stdout.decode("utf-8", "replace").strip()
    if not out:
        return {}
    try:
        return json.loads(out)
    except ValueError:
        return {"_bad": out}


def context(out):
    spec = out.get("hookSpecificOutput") or {}
    return spec.get("additionalContext", "") if spec.get("hookEventName") == "SessionStart" else ""


def kind(out):
    if "_bad" in out:
        return "BADJSON"
    return "NOTICE" if "FAST GATE" in context(out) else "QUIET"


fails = 0
for want, how, root in CASES:
    got = kind(run(how, root))
    if got != want:
        fails += 1
    print(f"{'ok ' if got == want else 'BAD'} want={want:6} got={got:6} {how:8} {os.path.basename(root)}")

extra = []
o = run("stdin", BUCKETS)
extra.append(("live-one" in context(o) and "run builder-02" in context(o)
              and "old-one" not in context(o) and "FAST GATE" not in context(o)
              and "live-one" in o.get("systemMessage", "") and "continue" in o.get("systemMessage", "")
              and "old-one" not in o.get("systemMessage", ""),
              "INDEX with OPEN + DONE rows -> only the OPEN slug listed, systemMessage names it"))
o = run("stdin", WITHOUT)
extra.append((kind(o) == "NOTICE" and "systemMessage" not in o,
              "no INDEX -> the gate notice alone, no systemMessage"))
# Payload cwd follows the shell's `cd`; CLAUDE_PROJECT_DIR is the launch root (forward
# slashes, as Claude Code sets it) and wins.
o = run("stdin", WITHOUT, project_dir=BUCKETS.replace(os.sep, "/"))
extra.append((kind(o) == "QUIET" and "live-one" in context(o),
              "CLAUDE_PROJECT_DIR = A, payload cwd = B -> A is read"))
o = run("stdin", MIX)
extra.append(("blocked-one" in context(o) and "[BLOCKED]" in context(o),
              "BLOCKED row -> listed with its status"))
extra.append(("y" * 200 in context(o) and "y" * 201 not in context(o),
              "300-char next action -> cut to 200"))
extra.append((r"pipe-one [OPEN]: a \| b" in context(o), r"next action holding an escaped \| -> kept whole"))
extra.append(("../x" not in context(o) and "escaped the scratch dir" not in context(o),
              "slug ../x -> dropped"))
o = run("stdin", MANY)
extra.append(("b0" not in context(o) and "b1 " not in context(o)
              and all(f"b{i} [OPEN]" in context(o) for i in range(2, 10))
              and "+2 more" in context(o),
              "10 OPEN rows -> the last 8 listed, then +2 more"))
o = run("stdin", BUCKETS, source="compact")
extra.append(("live-one" in context(o) and "systemMessage" not in o,
              "source compact -> additionalContext, no systemMessage"))
# Launched in a parent dir, then cd into the repo: the launch root has no scratch, cwd does.
o = run("stdin", BUCKETS, project_dir=WITHOUT.replace(os.sep, "/"))
extra.append(("live-one" in context(o),
              "CLAUDE_PROJECT_DIR without .claude/scratch, payload cwd with it -> cwd's buckets"))
for good, label in extra:
    if not good:
        fails += 1
    print(f"{'ok ' if good else 'BAD'} {label}")
total = len(CASES) + len(extra)
print(f"\n{total - fails}/{total} passed")
sys.exit(1 if fails else 0)
