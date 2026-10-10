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
import time
import uuid

HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kit-context.py")
tmp = tempfile.mkdtemp(prefix="kit-context-test-")
# The kit is off by default (kit_off.py): the fixture project, and the launch root one case moves
# to, are switched on the way /kit-on does it - the kit's rules copy.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_off import HEADER, RULES  # noqa: E402
for _root in (tmp, os.path.join(tmp, "elsewhere")):
    os.makedirs(os.path.join(_root, ".claude", "rules"))
    with open(os.path.join(_root, RULES), "wb") as _f:
        _f.write(HEADER + b" (test) -->\n")
# A caller running inside Claude Code has CLAUDE_PROJECT_DIR and CLAUDE_CODE_SESSION_ATTENDED
# set; every run gets the same env whether or not it is, and a case adds what it tests.
# The window env vars are stripped too: the caller's provider or 1M switch must not move a case.
ENV = {k: v for k, v in os.environ.items()
       if k not in ("CLAUDE_PROJECT_DIR", "CLAUDE_CODE_SESSION_ATTENDED",
                    "CLAUDE_CODE_DISABLE_1M_CONTEXT", "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
                    "DISABLE_COMPACT", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
                    "CLAUDE_CODE_USE_FOUNDRY")}
# Context markers and the per-session read state (kit_index.resumed) land in a private temp dir,
# test and hook alike, never in the real one.
PRIVATE_TMP = os.path.join(tmp, "_tmp")
os.makedirs(PRIVATE_TMP)
tempfile.tempdir = PRIVATE_TMP
ENV.update(TEMP=PRIVATE_TMP, TMP=PRIVATE_TMP, TMPDIR=PRIVATE_TMP)
sessions = []
SMALL = "claude-haiku-4-5-20251001"   # a 200K model: the band arithmetic below is of 200K


def synthetic():
    return {"type": "assistant", "isSidechain": False, "message": {"model": "<synthetic>", "usage": {
        "input_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        "output_tokens": 0}}}


def asst(used, sidechain=False, model_id=SMALL, sid=None):
    line = {"type": "assistant", "isSidechain": sidechain,
            "message": {"model": model_id, "usage": {
                "input_tokens": 2, "cache_creation_input_tokens": 1000,
                "cache_read_input_tokens": used - 1002, "output_tokens": 50}}}
    if sid:
        line["sessionId"] = sid
    return line


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
                       env=dict(ENV, **{"CLAUDE_PROJECT_DIR": tmp, **(env or {})}))
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

    # 2-4. one session: first crossing blocks, the stop after it tells the user once, the same
    # band later says nothing (a notice on every stop reached 56 in one session), the next band
    # blocks again
    s = session()
    ok(blocked(run(transcript(asst(100_000)), s), 50), "50% first time -> block naming 50%")
    ok(notice(run(transcript(asst(100_000)), s, stop_hook_active=True), 50)
       and quiet(run(transcript(asst(100_000)), s)),
       "the stop after the block -> notice once; 50% again later -> silent, no second block")
    ok(blocked(run(transcript(asst(120_000)), s), 60), "60% (next band) -> block again")

    # 5. a stop caused by our own block never blocks again
    s = session()
    run(transcript(asst(100_000)), s)
    ok(notice(run(transcript(asst(100_000)), s, stop_hook_active=True), 50),
       "stop_hook_active true after our block -> systemMessage only")

    # 6. agents still running = the task is not finished
    ok(quiet(run(transcript(asst(100_000)), session(), background=[{"id": "a1"}])),
       "background_tasks non-empty -> no output")

    # 7-8. the window comes from the last model attachment
    ok(quiet(run(transcript(model("claude-opus-5-5[1m]"), asst(300_000)), session())),
       "[1m] attachment: 300K of 1M = 30% -> no output")
    ok(quiet(run(transcript(asst(300_000)), session())),
       "no attachment but 300K used -> must be the 1M window, 30% -> no output")
    ok(blocked(run(transcript(asst(150_000)), session()), 75),
       "no attachment, Haiku replies: 150K of 200K = 75% -> block")

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
    ok(blocked(run(path, s), 50) and quiet(run(path, s)) and os.path.exists(marker),
       "synthetic zero-usage line after 50% -> still 50%: block, then silent, marker kept")

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

    # 22-30. the window is 1M unless the model is a known 200K one ([1m] never reaches the
    # transcript). Regression of 2026-09-29: Opus 5.5 at 130K read "65%", at 160K "80%".
    O55 = "claude-opus-5-5"
    ok(quiet(run(transcript(model(O55), asst(130_000, model_id=O55)), session())),
       "Opus 5.5 attachment: 130K of 1M = 13% -> no output")
    ok(quiet(run(transcript(asst(160_000, model_id=O55)), session())),
       "no attachment, Opus 5.5 replies: 160K of 1M = 16% -> no output")
    ok(blocked(run(transcript(model(O55), asst(500_000, model_id=O55)), session()), 50),
       "Opus 5.5: 500K of 1M = 50% -> block")
    ok(quiet(run(transcript(model("claude-sonnet-6"), asst(150_000)), session())),
       "an unknown future model is taken as 1M: 150K = 15% -> no output")
    ok(blocked(run(transcript(model("claude-opus-4-6"), asst(100_000)), session()), 50)
       and quiet(run(transcript(model("claude-opus-4-7"), asst(100_000)), session())),
       "Opus 4.6 is 200K (50% -> block), Opus 4.7 is 1M (10% -> no output)")
    ok(blocked(run(transcript(model("claude-sonnet-4-5-20250929"), asst(100_000)), session()), 50)
       and blocked(run(transcript(model("claude-opus-4-20250514"), asst(100_000)), session()), 50),
       "dated ids: Sonnet 4.5 and Opus 4 are 200K -> 50% -> block")
    ok(blocked(run(transcript(model(O55), asst(100_000, model_id=O55)), session(),
                   env={"CLAUDE_CODE_DISABLE_1M_CONTEXT": "1"}), 50),
       "CLAUDE_CODE_DISABLE_1M_CONTEXT=1 holds Opus 5.5 to 200K: 100K = 50% -> block")
    ok(blocked(run(transcript(model(O55), asst(100_000, model_id=O55)), session(),
                   env={"CLAUDE_CODE_USE_BEDROCK": "1"}), 50)
       and quiet(run(transcript(model(O55 + "[1m]"), asst(100_000, model_id=O55)), session(),
                     env={"CLAUDE_CODE_USE_BEDROCK": "1"})),
       "Bedrock: Opus 5.5 without [1m] is 200K (block), with [1m] is 1M (no output)")
    ok(blocked(run(transcript(model(O55), asst(200_000, model_id=O55)), session(),
                   env={"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "400000", "DISABLE_COMPACT": "1"}), 50)
       and quiet(run(transcript(model(O55), asst(200_000, model_id=O55)), session(),
                     env={"CLAUDE_CODE_MAX_CONTEXT_TOKENS": "400000"})),
       "MAX_CONTEXT_TOKENS=400K counts for a claude- id only with DISABLE_COMPACT")

    # 31-33. only this session's lines count: a stale transcript_path or a resumed session's
    # copied history must not carry the old session's usage into a new one
    s = session()
    ok(quiet(run(transcript(asst(180_000, sid="old-session")), s)),
       "every line from another sessionId -> 0 used -> no output")
    # the old session's line comes LAST, so without the filter the last line (90%) would win
    ok(quiet(run(transcript(asst(30_000, sid=s), asst(180_000, sid="old-session")), s)),
       "this session at 15%, a later old-session line at 90% -> this session's 15% -> no output")
    s = session()
    ok(blocked(run(transcript(asst(20_000, sid="old-session"), asst(100_000, sid=s)), s), 50),
       "this session's own lines still count: 100K of 200K = 50% -> block")

    # 34-45. the session digest (2026-10-07, after review): the block writes nothing and names
    # no path; once THIS session has written a bucket's STATE.md (its own transcript says so),
    # every later stop keeps <bucket>/digests/<session>.md current; STATE.md budget by band
    def digest(slug, sid):
        return os.path.join(tmp, ".claude", "scratch", slug, "digests", sid + ".md")

    def state(slug, path=None):
        """Write <slug>/STATE.md; with a transcript `path`, also record that this session wrote it."""
        p = os.path.join(tmp, ".claude", "scratch", slug, "STATE.md")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("# STATE\n")
        if path:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "assistant", "isSidechain": False, "message": {"content": [
                    {"type": "tool_use", "id": uuid.uuid4().hex, "name": "Write",
                     "input": {"file_path": p, "content": "# STATE"}}]}}) + "\n")

    s = session()
    path = transcript({"type": "user", "message": {"content": "keep the report in Hinglish"}},
                      asst(100_000))
    res = run(path, s)
    ok(blocked(res, 50) and "~60 lines" in res[1].get("reason", "") and "digests/" in res[1].get("reason", "")
       and not os.path.exists(os.path.join(tmp, ".claude", "scratch"))
       and "touched no bucket" in res[1].get("reason", "") and "parallel window" in res[1].get("reason", ""),
       "50% block: STATE at ~60 lines, digest promised, nothing written; no bucket -> open one, never another's")
    state("other")  # another session's STATE.md: only on disk, never in this transcript
    ok(notice(run(path, s, stop_hook_active=True), 50) and not os.path.exists(digest("other", s)),
       "the stop after the block: only another session's STATE.md exists -> no digest")
    state("task-a", path)
    ok(notice(run(path, s, stop_hook_active=True), 50) and os.path.isfile(digest("task-a", s))
       and "keep the report in Hinglish" in open(digest("task-a", s), encoding="utf-8").read(),
       "this session wrote task-a's STATE.md -> the digest lands there, user words verbatim")
    # The block names THIS session's bucket (parallel-window-resume F5): "other" is newer on disk.
    s2 = session()
    path2 = transcript(asst(100_000))
    state("task-a", path2)
    state("other")
    res = run(path2, s2)
    ok(blocked(res, 50) and "This session's bucket is `task-a`" in res[1].get("reason", "")
       and "`other`" not in res[1].get("reason", ""),
       "the block names the bucket this session wrote, not a newer one of another session")
    gi = os.path.join(tmp, ".claude", "scratch", "task-a", "digests", ".gitignore")
    ok(os.path.isfile(gi) and open(gi).read().strip().endswith("*"), "the digests folder ignores itself in git")
    before = os.path.getmtime(digest("task-a", s))
    ok(quiet(run(path, s)) and os.path.getmtime(digest("task-a", s)) == before,
       "same band, transcript unchanged -> silent, digest not rewritten")
    state("other")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "message": {"content": "then commit and push"}}) + "\n")
        f.write(json.dumps(asst(101_000)) + "\n")
    os.utime(path, (before + 5, before + 5))
    # Past the handoff, one rebuild per DIGEST_EVERY_S (D005): each reads the whole transcript, and
    # SessionEnd writes the digest whole anyway. The stamp is aged to let the next one through.
    stamp = os.path.join(PRIVATE_TMP, "kit-context-" + s + ".digest")
    ok(quiet(run(path, s)) and "then commit and push" not in open(digest("task-a", s), encoding="utf-8").read(),
       "a stop within 5 minutes of the last rebuild leaves the digest as it is (D005)")
    os.utime(stamp, (time.time() - 400,) * 2)
    ok(quiet(run(path, s)) and "then commit and push" in open(digest("task-a", s), encoding="utf-8").read()
       and not os.path.exists(digest("other", s)),
       "5 minutes on, a later stop refreshes the digest; a newer STATE.md of another session does not move it")
    state("task-b", path)
    os.utime(stamp, (time.time() - 400,) * 2)
    ok(quiet(run(path, s)) and os.path.isfile(digest("task-b", s)),
       "this session hands off into task-b later -> the digest follows its newest handoff")
    # a symlinked or junctioned digests/ is never written through (it would leave the bucket)
    s3 = session()
    p3 = transcript(asst(100_000))
    run(p3, s3)
    state("linked", p3)
    outside = os.path.join(tmp, "outside")
    os.makedirs(outside)
    linked = False
    try:
        os.symlink(outside, os.path.join(tmp, ".claude", "scratch", "linked", "digests"), target_is_directory=True)
        linked = True
    except (OSError, NotImplementedError):
        linked = subprocess.run(["cmd", "/c", "mklink", "/J", os.path.join(tmp, ".claude", "scratch", "linked", "digests"),
                                 outside], capture_output=True).returncode == 0 if os.name == "nt" else False
    run(p3, s3, stop_hook_active=True)
    ok(linked and os.listdir(outside) == [], "a symlinked/junctioned digests/ is never written through")
    ok(quiet(run(transcript(asst(100_000)), session(), stop_hook_active=True)),
       "stop_hook_active from another hook's block, none of ours -> no notice")
    s2 = session()
    p2 = transcript(asst(100_000))
    run(p2, s2)
    state("task-c", p2)
    os.rename(os.path.join(tmp, RULES), os.path.join(tmp, RULES + ".away"))
    ok(notice(run(p2, s2, stop_hook_active=True, env={"CLAUDE_PROJECT_DIR": os.path.join(tmp, "elsewhere")}), 50)
       and not os.path.exists(digest("task-c", s2)),
       "the payload cwd's project is switched off -> no digest written into it")
    os.rename(os.path.join(tmp, RULES + ".away"), os.path.join(tmp, RULES))
    s = session()
    r70 = run(transcript(asst(140_000)), s)
    r80 = run(transcript(asst(160_000)), s)
    ok(blocked(r70, 70) and "~100 lines" in r70[1].get("reason", "")
       and blocked(r80, 80) and "~120 lines" in r80[1].get("reason", ""),
       "STATE budget grows with the band: 70% -> ~100 lines, 80% -> ~120 lines")

    # 46-48. the timeline entry (bucket handoff-timeline): every stop, whatever the %, headless or
    # with an agent still running - a killed window fires no SessionEnd.
    def entry(slug, sid):
        p = os.path.join(tmp, ".claude", "scratch", slug, "digests", sid + ".json")
        return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else None
    s = session()
    p = transcript(asst(30_000))
    state("task-d", p)
    ok(quiet(run(p, s)) and (entry("task-d", s) or {}).get("pct") == 15
       and os.path.isfile(os.path.join(tmp, ".claude", "scratch", "task-d", "SESSIONS.md")),
       "a stop at 15% that wrote STATE.md: silent, but its timeline entry (with its %) and SESSIONS.md exist")
    s = session()
    p = transcript(asst(30_000))
    state("task-e", p)
    ok(quiet(run(p, s, background=[{"type": "agent"}])) and entry("task-e", s),
       "an agent still running: no notice, the entry is still written")
    s = session()
    p = transcript(asst(30_000))
    state("task-f", p)
    ok(quiet(run(p, s, env={"CLAUDE_CODE_SESSION_ATTENDED": "0"})) and entry("task-f", s),
       "headless: no block, the entry is still written")

    # 12-13. fail open
    ok(quiet(run(os.path.join(tmp, "nope.jsonl"), session())), "missing transcript -> no output, exit 0")
    ok(quiet(run(None, session(), raw=b"{not json")), "non-JSON stdin -> no output, exit 0")

    # 14. Each Stop reads only what the transcript gained since the last one (kit_index.resumed,
    # bucket kit-default-off-optimize): the same usage as a whole read; a line still being written
    # waits for the next turn.
    import importlib.util
    spec = importlib.util.spec_from_file_location("kit_context", HOOK)
    kctx = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(kctx)
    p, c = transcript(asst(60_000)), os.path.join(PRIVATE_TMP, "case14.usage")
    first = kctx.usage(p, "", c)
    late = json.dumps(asst(90_000)) + "\n"
    with open(p, "a", encoding="utf-8") as f:
        f.write(late[:25])
    torn = kctx.usage(p, "", c)
    with open(p, "a", encoding="utf-8") as f:
        f.write(late[25:])
    ok(first == torn == (60_000, 200_000) and kctx.usage(p, "", c) == kctx.usage(p) == (90_000, 200_000)
       and os.path.isfile(c), "usage from a kept state = a whole read; a torn last line waits for the next turn")
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
