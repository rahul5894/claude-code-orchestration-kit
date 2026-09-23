"""Self-contained check for kit-context.py. Run from anywhere:
python kit-context_test.py
Builds its own transcripts in a temp dir, feeds the hook a Stop payload per case, and deletes
the tree and every band marker it caused on the way out."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit-context.py")
tmp = tempfile.mkdtemp(prefix="kit-context-test-")
# A caller running inside Claude Code has CLAUDE_PROJECT_DIR and CLAUDE_CODE_SESSION_ATTENDED
# set; every run gets the same env whether or not it is, and a case adds what it tests.
ENV = {k: v for k, v in os.environ.items()
       if k not in ("CLAUDE_PROJECT_DIR", "CLAUDE_CODE_SESSION_ATTENDED")}
sessions = []


def synthetic():
    return {"type": "assistant", "isSidechain": False, "message": {"model": "<synthetic>", "usage": {
        "input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        "output_tokens": 0}}}


def asst(used, sidechain=False):
    return {"type": "assistant", "isSidechain": sidechain,
            "message": {"model": "claude-opus-5-5", "usage": {
                "input_tokens": 2, "cache_creation_input_tokens": 1000,
                "cache_read_input_tokens": used - 1002, "output_tokens": 50}}}


def model(model_id):
    return {"type": "attachment", "attachment": {"type": "model", "identity": {
        "modelId": model_id, "marketingName": "x"}}}


def transcript(*lines):
    path = os.path.join(tmp, uuid.uuid4().hex + ".jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return path


def session():
    sid = "test-" + uuid.uuid4().hex
    sessions.append(sid)
    return sid


def run(path, sid, stop_hook_active=False, background=None, raw=None, env=None):
    """(returncode, parsed stdout or None for empty, or the raw text if it is not JSON)."""
    if raw is None:
        raw = json.dumps({"session_id": sid, "transcript_path": path, "cwd": tmp,
                          "hook_event_name": "Stop", "stop_hook_active": stop_hook_active,
                          "background_tasks": background or [], "session_crons": []}).encode("utf-8")
    p = subprocess.run([sys.executable, HOOK], input=raw, capture_output=True,
                       env=dict(ENV, **(env or {})))
    out = p.stdout.decode("utf-8", "replace").strip()
    if not out:
        return p.returncode, None
    try:
        return p.returncode, json.loads(out)
    except ValueError:
        return p.returncode, out


def blocked(res, pct):
    code, out = res
    return (code == 0 and isinstance(out, dict) and out.get("decision") == "block"
            and f"{pct}%" in out.get("reason", "") and "STATE.md" in out.get("reason", ""))


def notice(res, pct):
    code, out = res
    return (code == 0 and isinstance(out, dict) and "decision" not in out
            and f"{pct}%" in out.get("systemMessage", ""))


def quiet(res):
    return res == (0, None)


cases = []


def ok(cond, label):
    cases.append((bool(cond), label))


try:
    # 1. under the threshold says nothing
    ok(quiet(run(transcript(asst(80_000)), session())), "40% of 200K -> no output")

    # 2-4. one session: first crossing blocks, the same band again only notifies, the next
    # band blocks again
    s = session()
    ok(blocked(run(transcript(asst(100_000)), s), 50), "50% first time -> block naming 50%")
    ok(notice(run(transcript(asst(100_000)), s), 50),
       "50% again, same session -> systemMessage only, no second block")
    ok(blocked(run(transcript(asst(120_000)), s), 60), "60% (next band) -> block again")

    # 5. a stop caused by our own block never blocks again
    ok(notice(run(transcript(asst(100_000)), session(), stop_hook_active=True), 50),
       "stop_hook_active true -> systemMessage only")

    # 6. agents still running = the task is not finished
    ok(quiet(run(transcript(asst(100_000)), session(), background=[{"id": "a1"}])),
       "background_tasks non-empty -> no output")

    # 7-8. the window comes from the last model attachment
    ok(quiet(run(transcript(model("claude-opus-5-5[1m]"), asst(300_000)), session())),
       "[1m] attachment: 300K of 1M = 30% -> no output")
    ok(quiet(run(transcript(asst(300_000)), session())),
       "no attachment but 300K used -> must be the 1M window, 30% -> no output")
    ok(blocked(run(transcript(asst(150_000)), session()), 75),
       "no attachment: 150K of 200K = 75% -> block")

    # 9. a subagent's usage in the main transcript is not the main context
    ok(blocked(run(transcript(asst(100_000), asst(20_000, sidechain=True)), session()), 50),
       "last main-chain usage wins over a later isSidechain:true line")

    # 10-11. falling under the threshold (after /compact) clears the marker
    s = session()
    marker = os.path.join(tempfile.gettempdir(), "kit-context-" + s)
    first = run(transcript(asst(100_000)), s)
    had = os.path.exists(marker)
    ok(blocked(first, 50) and had, "crossing writes the band marker")
    low = run(transcript(asst(40_000)), s)
    ok(quiet(low) and not os.path.exists(marker)
       and blocked(run(transcript(asst(100_000)), s), 50),
       "pct under 45 -> marker removed, next crossing blocks again")

    # 14-16. Fable 5.1 is a 1M window with no "[1m]" in its id
    ok(quiet(run(transcript(model("claude-fable-5-1"), asst(150_000)), session())),
       "Fable attachment: 150K of 1M = 15% -> no output")
    ok(quiet(run(transcript(model("claude-fable-5-1"), asst(300_000)), session())),
       "Fable attachment: 300K of 1M = 30% -> no output")
    ok(blocked(run(transcript(model("claude-fable-5-1"), asst(500_000)), session()), 50),
       "Fable attachment: 500K of 1M = 50% -> block")

    # 17. a <synthetic> zero-usage line does not reset the measured usage
    s = session()
    marker = os.path.join(tempfile.gettempdir(), "kit-context-" + s)
    path = transcript(asst(100_000), synthetic())
    ok(blocked(run(path, s), 50) and notice(run(path, s), 50) and os.path.exists(marker),
       "synthetic zero-usage line after 50% -> still 50%: block, then notice, marker kept")

    # 18-19. a background shell is not an unfinished task; a background agent is
    ok(blocked(run(transcript(asst(100_000)), session(),
                   background=[{"type": "shell", "status": "running"}]), 50),
       "background_tasks = shell only -> block as if none ran")
    ok(quiet(run(transcript(asst(100_000)), session(),
                 background=[{"type": "shell"}, {"type": "local_agent", "status": "running"}])),
       "background agent-type entry -> no output")

    # 20. headless (claude -p) never blocks and never marks
    s = session()
    ok(quiet(run(transcript(asst(120_000)), s, env={"CLAUDE_CODE_SESSION_ATTENDED": "0"}))
       and not os.path.exists(os.path.join(tempfile.gettempdir(), "kit-context-" + s)),
       "CLAUDE_CODE_SESSION_ATTENDED=0 at 60% -> no output, no marker")

    # 12-13. fail open
    ok(quiet(run(os.path.join(tmp, "nope.jsonl"), session())), "missing transcript -> no output, exit 0")
    ok(quiet(run(None, session(), raw=b"{not json")), "non-JSON stdin -> no output, exit 0")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
    for sid in sessions:
        try:
            os.remove(os.path.join(tempfile.gettempdir(), "kit-context-" + sid))
        except OSError:
            pass

fails = sum(1 for good, _ in cases if not good)
for good, label in cases:
    print(f"{'ok ' if good else 'BAD'} {label}")
print(f"\n{len(cases) - fails}/{len(cases)} passed")
sys.exit(1 if fails else 0)
