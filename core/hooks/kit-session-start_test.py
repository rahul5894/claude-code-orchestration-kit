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


PRIVATE_TMP = os.path.join(tmp, "_tmp")  # window records land here, never in the real temp dir
os.makedirs(PRIVATE_TMP)


def run(how, root, project_dir=None, source="startup", pid=None, sid=None, transcript=None):
    """Parsed stdout: {} when silent, {"_bad": text} when it is not JSON. `pid` plays the
    window (env CLAUDE_PID); without it the run has none, whatever window runs the test."""
    # The hook prefers CLAUDE_PROJECT_DIR; a caller inside Claude Code has it set, so every run
    # starts from an env without it and only the case that tests it puts it back.
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PROJECT_DIR", "CLAUDE_PID")}
    env.update(TEMP=PRIVATE_TMP, TMP=PRIVATE_TMP, TMPDIR=PRIVATE_TMP)
    if project_dir:
        env["CLAUDE_PROJECT_DIR"] = project_dir
    if pid:
        env["CLAUDE_PID"] = str(pid)
    if how == "stdin":
        # Raw UTF-8 bytes, the way JSON.stringify feeds the real hook. text=True would
        # encode with the locale codec and the non-ASCII case could never run.
        payload = {"cwd": root, "source": source}
        if sid:
            payload.update(session_id=sid, transcript_path=transcript or "")
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
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
# After a compaction the newest open STATE.md rides along; startup never carries it.
for slug, body in (("live-one", "Next: LIVE-CODEWORD\n"), ("old-one", "DONE-CODEWORD\n")):
    os.makedirs(os.path.join(BUCKETS, ".claude", "scratch", slug), exist_ok=True)
    with open(os.path.join(BUCKETS, ".claude", "scratch", slug, "STATE.md"), "w", encoding="utf-8") as f:
        f.write(body)
o = run("stdin", BUCKETS, source="compact")
extra.append(("LIVE-CODEWORD" in context(o) and "DONE-CODEWORD" not in context(o),
              "source compact -> the open bucket's STATE.md is in the context, a DONE one's is not"))
o = run("stdin", BUCKETS)
extra.append(("LIVE-CODEWORD" not in context(o), "source startup -> no STATE.md content"))
for i, slug in enumerate(("b3", "b7")):
    os.makedirs(os.path.join(MANY, ".claude", "scratch", slug))
    p = os.path.join(MANY, ".claude", "scratch", slug, "STATE.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(f"STATE-OF-{slug}\n" + ("z" * 9000 if slug == "b7" else ""))
    os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
o = run("stdin", MANY, source="compact")
extra.append(("STATE-OF-b7" in context(o) and "STATE-OF-b3" not in context(o)
              and "z" * 5900 in context(o) and "z" * 6001 not in context(o) and "cut at 6000" in context(o),
              "two open STATE.md -> only the newest, cut at 6000 bytes with a marker"))
# The newest "STATE.md" is a directory: the next newest readable one is used instead.
os.makedirs(os.path.join(MANY, ".claude", "scratch", "b9", "STATE.md"))
o = run("stdin", MANY, source="compact")
extra.append(("STATE-OF-b7" in context(o) and "hookSpecificOutput" in o,
              "newest STATE.md is a directory -> falls back to the older readable one"))
# A cut in the middle of a UTF-8 character must not break the JSON or silence the hook.
CUT = bucket_project("cut", True, [("u8", "OPEN", "x")])
os.makedirs(os.path.join(CUT, ".claude", "scratch", "u8"))
with open(os.path.join(CUT, ".claude", "scratch", "u8", "STATE.md"), "wb") as f:
    f.write(b"a" * 5999 + "é".encode("utf-8") + b"tail\xff\xfe")
o = run("stdin", CUT, source="compact")
extra.append(("_bad" not in o and "a" * 5999 in context(o) and "u8 [OPEN]" in context(o),
              "multi-byte char cut at the cap, invalid bytes -> valid JSON, text kept"))
# kit-off in the project silences the new path too.
open(os.path.join(CUT, ".claude", "kit-off"), "w").close()
o = run("stdin", CUT, source="compact")
extra.append(("a" * 100 not in context(o), "kit-off + compact -> no STATE.md content"))
# A cloned repo's STATE.md as a symlink to a file outside the scratch dir is never read.
LINK = bucket_project("link", True, [("ln", "OPEN", "x")])
os.makedirs(os.path.join(LINK, ".claude", "scratch", "ln"))
secret = os.path.join(tmp, "secret.txt")
with open(secret, "w", encoding="utf-8") as f:
    f.write("SECRET-OUTSIDE-SCRATCH\n")
try:
    os.symlink(secret, os.path.join(LINK, ".claude", "scratch", "ln", "STATE.md"))
except OSError:
    print("SKIP symlinked STATE.md (this machine cannot create symlinks); total drops by one")
else:
    o = run("stdin", LINK, source="compact")
    extra.append(("SECRET-OUTSIDE-SCRATCH" not in context(o) and "ln [OPEN]" in context(o),
                  "STATE.md symlinked outside the scratch dir -> not read, bucket still listed"))
# Launched in a parent dir, then cd into the repo: the launch root has no scratch, cwd does.
o = run("stdin", BUCKETS, project_dir=WITHOUT.replace(os.sep, "/"))
extra.append(("live-one" in context(o),
              "CLAUDE_PROJECT_DIR without .claude/scratch, payload cwd with it -> cwd's buckets"))
# INDEX shapes models write besides the /task table (2026-09-29: Strem-setup's bullet INDEX left
# all 3 open buckets unseen, and `IN PROGRESS` was skipped as not OPEN/BLOCKED).
BUL = os.path.join(tmp, "bullets")
for slug in ("fail-over", "stall", "gone"):
    os.makedirs(os.path.join(BUL, ".claude", "scratch", slug))
with open(os.path.join(BUL, "CLAUDE.md"), "w", encoding="utf-8") as f:
    f.write("# x\n| **FAST GATE — agents run this** | `make lint` | 4 s |\n")
with open(os.path.join(BUL, ".claude", "scratch", "INDEX.md"), "w", encoding="utf-8") as f:
    f.write("# Buckets\n- fail-over — OPEN — copy failover next\n- stall — BLOCKED — waits on the user\n"
            "- gone — DONE — in _closed/\n- see the notes — for background\n")
o = run("stdin", BUL)
extra.append(("fail-over [OPEN]: copy failover next" in context(o) and "stall [BLOCKED]" in context(o)
              and "gone" not in context(o) and "see" not in o.get("systemMessage", ""),
              "bullet INDEX -> OPEN and BLOCKED listed, DONE and a prose bullet are not"))
PROG = bucket_project("progress", True, [("doing", "IN PROGRESS", "next step"), ("fin", "COMPLETED", "x"),
                                         ("OPEN", "active", "legend row")])
os.makedirs(os.path.join(PROG, ".claude", "scratch", "doing"))
o = run("stdin", PROG)
extra.append(("doing [IN PROGRESS]" in context(o) and "fin" not in context(o)
              and "legend row" not in context(o),
              "IN PROGRESS with its folder -> open; COMPLETED and a legend row | OPEN | active | -> not"))
# /continue resumes the newest handoff without asking; a STATE.md that says CLOSED is skipped.
NEW = bucket_project("newest", True, [("older", "OPEN", "a"), ("newer", "OPEN", "b"), ("shut", "OPEN", "c")])
for i, (slug, body) in enumerate((("older", "Status: OPEN\n"), ("newer", "Status: OPEN\n"),
                                  ("shut", "Updated: x   Status: CLOSED 2026-09-29\n"))):
    os.makedirs(os.path.join(NEW, ".claude", "scratch", slug))
    p = os.path.join(NEW, ".claude", "scratch", slug, "STATE.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(body)
    os.utime(p, (1_700_000_000 + i, 1_700_000_000 + i))
o = run("stdin", NEW)
extra.append(("newer [OPEN]: b (newest handoff)" in context(o) and "older [OPEN]: a\n" in context(o)
              and "shut [OPEN]: c\n" in context(o) and "ask the user which" in context(o)
              and o.get("systemMessage", "").endswith("it asks which (newest: newer)."),
              "3 open, newest STATE.md says CLOSED -> 2 free handoffs: newest marked, /continue asks"))
os.remove(os.path.join(NEW, ".claude", "scratch", "older", "STATE.md"))
o = run("stdin", NEW)
extra.append((o.get("systemMessage", "").endswith("resume newer."),
              "one free handoff left -> /continue resumes it unasked"))

# Parallel windows (D001): two windows each hand off and /clear; each gets ITS task back, not the
# one newest handoff. A window is env CLAUDE_PID; both must be live processes.
PAR = bucket_project("parallel", True, [("task-x", "OPEN", "x next"), ("task-y", "OPEN", "y next")])


def wrote_state(name, slug, read=False):
    """A transcript in which a session wrote (or only read) <slug>/STATE.md."""
    path = os.path.join(tmp, name + ".jsonl")
    target = os.path.join(PAR, ".claude", "scratch", slug, "STATE.md")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if not os.path.isfile(target):
        with open(target, "w", encoding="utf-8") as f:
            f.write(f"# STATE - {slug}\nStatus: OPEN\nSTATE-OF-{slug}\n")
    use = {"type": "tool_use", "id": name, "name": "Read" if read else "Write", "input": {"file_path": target}}
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "assistant", "isSidechain": False, "message": {"content": [use]}}) + "\n")
    return path


tx, ty = wrote_state("tx", "task-x"), wrote_state("ty", "task-y")
os.utime(os.path.join(PAR, ".claude", "scratch", "task-x", "STATE.md"), (1_700_000_000, 1_700_000_000))
win_a = os.getpid()                       # this test process: alive for every run below
other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
win_b = other.pid
dead = subprocess.Popen([sys.executable, "-c", "pass"])
dead.wait()
try:
    run("stdin", PAR, pid=win_a, sid="sa1", transcript=tx)          # window A works on task-x
    run("stdin", PAR, pid=win_b, sid="sb1", transcript=ty)          # window B on task-y (newest)
    a2 = run("stdin", PAR, source="clear", pid=win_a, sid="sa2", transcript=os.path.join(tmp, "sa2.jsonl"))
    b2 = run("stdin", PAR, source="clear", pid=win_b, sid="sb2", transcript=os.path.join(tmp, "sb2.jsonl"))
    extra.append(("task-x [OPEN]: x next (this window's task)" in context(a2)
                  and "task-y [OPEN]: y next (open in another window)" in context(a2)
                  and "resume task-x (this window's task)" in a2.get("systemMessage", ""),
                  "window A /clear -> its own task-x, task-y is open in window B (not the newest)"))
    extra.append(("task-y [OPEN]: y next (this window's task)" in context(b2)
                  and "task-x [OPEN]: x next (open in another window)" in context(b2),
                  "window B /clear -> its own task-y; task-x held by A's lineage before A's new session touched it"))
    c = run("stdin", PAR, pid=dead.pid, sid="sc1", transcript=os.path.join(tmp, "sc1.jsonl"))
    extra.append(("next (this window's task)" not in context(c) and "x next (open in another window)" in context(c) and "y next (open in another window)" in context(c)
                  and "<slug> to take one here" in c.get("systemMessage", ""),
                  "a third window at startup -> both tasks busy, nothing resumed unasked"))
    # A closed window holds nothing: its record is dropped and its bucket is free again.
    other.kill()
    other.wait()
    d = run("stdin", PAR, pid=win_a, sid="sa3", transcript=tx, source="compact")
    extra.append(("task-y [OPEN]: y next (newest handoff)" in context(d)
                  and not os.path.exists(os.path.join(PRIVATE_TMP, f"kit-window-{win_b}.json")),
                  "window B closed -> its claim is dropped, task-y is free again"))
    extra.append(("task-x's STATE.md" in context(d) and "STATE-OF-task-x" in context(d)
                  and "STATE-OF-task-y" not in context(d),
                  "compact -> this session's own STATE.md rides along, not the newer one of another task"))
    e = run("stdin", PAR, source="clear", pid=99999999, sid="se", transcript=os.path.join(tmp, "se.jsonl"))
    extra.append(("next (this window's task)" not in context(e) and e.get("systemMessage", "").endswith(
                  "resume task-y. Open in another window: task-x.")
                  and "task-x [OPEN]: x next (open in another window)" in context(e),
                  "/clear in a window with no record -> no lineage; task-x busy in A, task-y free"))
    rx = wrote_state("rx", "task-x", read=True)
    f2 = run("stdin", PAR, source="resume", pid=win_a, sid="sa4", transcript=rx)
    extra.append(("task-x [OPEN]: x next (this window's task)" in context(f2),
                  "resume of a session that only READ task-x's STATE.md (a /continue) -> task-x is its own"))
finally:
    other.kill()
for good, label in extra:
    if not good:
        fails += 1
    print(f"{'ok ' if good else 'BAD'} {label}")
total = len(CASES) + len(extra)
print(f"\n{total - fails}/{total} passed")
sys.exit(1 if fails else 0)
