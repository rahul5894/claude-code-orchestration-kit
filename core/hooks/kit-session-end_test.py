"""Self-contained check for kit-session-end.py. Run from anywhere: python kit-session-end_test.py
Runs the hook as Claude Code does (JSON on stdin) against projects it builds in a temp dir. The
caller's CLAUDE_PID is stripped and TEMP points at a private dir, so a run inside Claude Code
never writes the real window's record."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "kit-session-end.py")
sys.path.insert(0, HERE)
from kit_off import HEADER, RULES  # noqa: E402
tmp = tempfile.mkdtemp(prefix="kit-session-end-test-")
cases = []
SID = "dddddddd-0000-4000-8000-000000000001"


def ok(cond, label):
    cases.append((bool(cond), label))


def run(payload, root, extra=None):
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_PID", "CLAUDE_PROJECT_DIR",
                                                           "CLAUDE_CODE_SESSION_ATTENDED")}
    private = os.path.join(tmp, "temp")
    os.makedirs(private, exist_ok=True)
    env.update({"TEMP": private, "TMP": private, "TMPDIR": private, "CLAUDE_PROJECT_DIR": root,
                "CLAUDE_CONFIG_DIR": os.path.join(tmp, "cfg")}, **(extra or {}))
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    return subprocess.run([sys.executable, HOOK], input=raw, capture_output=True, env=env, timeout=60)


def project(name, on=True):
    root = os.path.join(tmp, name)
    os.makedirs(os.path.join(root, ".claude", "scratch", "alpha"))
    if on:  # the kit is off by default; /kit-on writes its rules copy (kit_off.py)
        os.makedirs(os.path.join(root, ".claude", "rules"))
        with open(os.path.join(root, RULES), "wb") as f:
            f.write(HEADER + b" (test) -->\n")
    return root


def transcript(root, sid=SID, touch=True):
    folder = os.path.join(tmp, "cfg", "projects", "p")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, sid + ".jsonl")
    state = os.path.join(root, ".claude", "scratch", "alpha", "STATE.md")
    lines = [{"type": "user", "isSidechain": False, "sessionId": sid, "timestamp": "2026-10-09T05:00:00Z",
              "message": {"role": "user", "content": "small task, 20% context"}}]
    if touch:
        lines.append({"type": "assistant", "isSidechain": False, "sessionId": sid, "timestamp": "2026-10-09T05:01:00Z",
                      "message": {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Write",
                                                                    "input": {"file_path": state, "content": "# STATE\n## Next action\ngo\n"}}]}})
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(json.dumps(x) for x in lines) + "\n")
    with open(state, "w", encoding="utf-8") as f:
        f.write("# STATE\n## Next action\ngo\n")
    return path


def digests(root):
    d = os.path.join(root, ".claude", "scratch", "alpha", "digests")
    return sorted(f for f in os.listdir(d) if not f.startswith(".")) if os.path.isdir(d) else []


try:
    root = project("p1")
    t = transcript(root)
    r = run({"session_id": SID, "transcript_path": t, "cwd": root, "reason": "clear"}, root)
    ok(r.returncode == 0 and r.stdout == b"", "exit 0 and silent (Claude Code discards SessionEnd output)")
    ok(digests(root) == [SID + ".json", SID + ".md", SID + ".state.md"],
       "a session under 45% that wrote STATE.md: entry, verbatim digest and snapshot")
    sessions = os.path.join(root, ".claude", "scratch", "alpha", "SESSIONS.md")
    ok(os.path.isfile(sessions) and f"## S1 · {SID}" in open(sessions, encoding="utf-8").read(),
       "SESSIONS.md lists the session")

    root2 = project("p2", on=False)
    t2 = transcript(root2)
    r = run({"session_id": SID, "transcript_path": t2, "cwd": root2}, root2)
    ok(r.returncode == 0 and digests(root2) == [], "a project with the kit off: nothing written")

    root3 = project("p3")
    r = run(b"\xff not json", root3)
    ok(r.returncode == 0 and r.stdout == b"" and digests(root3) == [], "garbage on stdin: exit 0, nothing written")
    r = run({"session_id": SID, "cwd": root3}, root3)
    ok(r.returncode == 0 and digests(root3) == [], "no transcript_path: nothing written")

    root4 = project("p4")
    t4 = transcript(root4, sid="dddddddd-0000-4000-8000-000000000004", touch=False)
    r = run({"session_id": "dddddddd-0000-4000-8000-000000000004", "transcript_path": t4, "cwd": root4}, root4)
    ok(r.returncode == 0 and digests(root4) == [], "a session that touched no bucket: nothing written")

    root5 = project("p5")
    t5 = transcript(root5)
    r = run({"session_id": SID, "transcript_path": t5, "cwd": root5}, root5,
            {"CLAUDE_CODE_SESSION_ATTENDED": "0", "PYTHONSAFEPATH": "1"})
    ok(r.returncode == 0 and SID + ".md" in digests(root5),
       "headless and PYTHONSAFEPATH=1: still recorded (the hook adds its own folder to sys.path)")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

fails = sum(1 for good, _ in cases if not good)
for good, label in cases:
    print(f"{'ok ' if good else 'BAD'} {label}")
print(f"\n{len(cases) - fails}/{len(cases)} passed")
sys.exit(1 if fails else 0)
