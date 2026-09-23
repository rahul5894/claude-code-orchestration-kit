"""Self-test for kit_off: every kit hook, fed a payload that makes it speak or write, must go
silent - no stdout, no file written - once the project holds .claude/kit-off, and must still
speak without it (else "silent" could mean "broken"). Temp dirs only; deletes them on exit.
Run: python kit_off_test.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
tmp = tempfile.mkdtemp(prefix="kit-off-test-")
fails = []


def ok(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)


def project(off):
    root = tempfile.mkdtemp(dir=tmp)
    scratch = os.path.join(root, ".claude", "scratch")
    os.makedirs(os.path.join(scratch, "alpha"))
    with open(os.path.join(scratch, "INDEX.md"), "w", encoding="utf-8") as f:
        f.write("| slug | status | updated | next action |\n|---|---|---|---|\n"
                "| alpha | OPEN | 2026-09-23 | next |\n")
    with open(os.path.join(scratch, "alpha", "DECISIONS.md"), "w", encoding="utf-8") as f:
        f.write("- D001 use X\n")
    with open(os.path.join(root, "big.md"), "w", encoding="utf-8") as f:
        f.write("line\n" * 400)
    usage = {"input_tokens": 2, "cache_creation_input_tokens": 1000,
             "cache_read_input_tokens": 150_000, "output_tokens": 50}
    with open(os.path.join(root, "t.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "assistant", "isSidechain": False,
                            "message": {"model": "claude-opus-5-5", "usage": usage}}) + "\n")
    if off:
        with open(os.path.join(root, ".claude", "kit-off"), "w", encoding="utf-8") as f:
            f.write("")
    return root


def run(hook, root, payload):
    env = dict(os.environ, CLAUDE_PROJECT_DIR=root)
    env.pop("CLAUDE_CODE_SESSION_ATTENDED", None)
    before = sorted(os.path.join(d, n) for d, _, ns in os.walk(root) for n in ns)
    p = subprocess.run([sys.executable, os.path.join(HERE, hook)], cwd=root, env=env,
                       input=json.dumps(dict(payload, cwd=root)).encode("utf-8"), capture_output=True)
    after = sorted(os.path.join(d, n) for d, _, ns in os.walk(root) for n in ns)
    return p.returncode, p.stdout.decode("utf-8", "replace").strip(), after != before


CASES = [
    ("md-guard.py", lambda r: {"tool_name": "Read", "tool_input": {"file_path": os.path.join(r, "big.md")}}),
    ("kit-session-start.py", lambda r: {"source": "startup"}),
    ("kit-subagent-start.py", lambda r: {"agent_type": "builder"}),
    ("kit-subagent-report.py", lambda r: {"agent_type": "builder", "agent_id": "a1",
                                          "last_assistant_message": "done"}),
    ("kit-context.py", lambda r: {"session_id": "kit-off-" + os.path.basename(r),
                                  "transcript_path": os.path.join(r, "t.jsonl"),
                                  "hook_event_name": "Stop", "stop_hook_active": False}),
]
try:
    for hook, payload in CASES:
        on, off = project(False), project(True)
        rc, out, wrote = run(hook, on, payload(on))
        ok(rc == 0 and (out or wrote), f"{hook}: kit on -> speaks or writes (rc={rc})")
        rc, out, wrote = run(hook, off, payload(off))
        ok(rc == 0 and not out and not wrote, f"{hook}: .claude/kit-off -> silent, writes nothing")
    # ...except md-guard's read-only write guard: any shell can create the marker, so the
    # marker must not be what lifts the one write boundary refuter and debugger have.
    off = project(True)
    rc, out, _ = run("md-guard.py", off, {"tool_name": "Bash", "agent_type": "refuter",
                                         "tool_input": {"command": "mkdir -p x"}})
    ok('"deny"' in out, "md-guard: .claude/kit-off does NOT lift the read-only write guard")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
    for f in os.listdir(tempfile.gettempdir()):
        if f.startswith("kit-context-kit-off-"):
            os.remove(os.path.join(tempfile.gettempdir(), f))

print(f"{2 * len(CASES) + 1 - len(fails)}/{2 * len(CASES) + 1} passed")
sys.exit(1 if fails else 0)
