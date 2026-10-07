"""Stop hook: at 45% context, the finished turn hands off and the user is told to /clear.

The user never watches the context meter, and past about half of it the model's grip on a
long task degrades. No hook payload carries context usage or the window (probed on Claude Code
2.1.284; only the statusline gets them), so it is read from the transcript: input +
cache_creation + cache_read tokens of the LAST main-chain assistant line (a "<synthetic>" line
or one whose counts sum to 0 is skipped), over the window of the session's model - see
window(). Only lines of THIS session count: a line whose sessionId is not the payload's
session_id (a stale transcript_path, the copied history of a resumed session) is skipped, so
a new session starts from 0 whatever file the payload names.

A stop while a background task other than a shell runs is not a finished task and says
nothing. A headless session (CLAUDE_CODE_SESSION_ATTENDED == "0") says nothing either: no
user reads the notice and a block would only spend a turn. The first stop in
each 10-point band from 45% (45, 55, 65...) returns `decision: block` with REASON, which goes
to the model: write the handoff into the open bucket's STATE.md, then tell the user. The stop
that follows the block shows NOTICE to the user once; later stops in the same band say
nothing. The band reached is kept per session in
the temp dir and removed once usage falls under 45% (after a compaction), so the next
crossing blocks again. Transcripts reach tens of MB: only lines containing `"usage"` or
`"modelId"` are parsed.

Before the block it writes the session digest (kit_digest.py: every user message and answer
verbatim, the tool trail, output excerpts; no model call) to
<project>/.claude/scratch/_sessions/<session>.md and names it in REASON, and every later stop
of the session rewrites it if the transcript is newer, so the digest reaches the last turn
before /clear. REASON sizes STATE.md by the band (60/80/100/120 lines). Measured 2026-10-07 on
4 real handoff chains: STATE.md alone let a cold reader answer 63.4% of 80 probes, STATE.md +
digest 94.7%; Claude Code's own /compact 72.5% (bucket kit-2.1.292-optimize, F13).

Exit 0 always. Any crash = silence (fail open, dev tool). Writes the temp-dir band marker and
the digest only; a digest that fails to write never costs the block.
Self-check: python kit-context_test.py
"""
import json
import os
import re
import sys
import tempfile

# The hook's own folder, explicitly: under PYTHONSAFEPATH=1 (or python -P / -I) the script dir
# is not on sys.path, the import fails and the hook exits 1 - which fails open (refuter-02).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_off import kit_off  # noqa: E402
try:
    import kit_digest  # noqa: E402
except Exception:  # an install missing the module still hands off, just without a digest
    kit_digest = None

THRESHOLD = 45
BAND = 10
WINDOW = 200_000
WINDOW_1M = 1_000_000
UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
# family, major, minor of a Claude model id; a date (-20250514) or a -v1:0 suffix is no minor.
FAMILY = re.compile(r"claude-(opus|sonnet|haiku|fable)-(\d+)(?:-(\d{1,2}))?(?![0-9])")
TRUTHY = ("1", "true", "yes", "on")
REASON = ("orchestration-kit: context is at {pct}% ({used}K of {window}K). Hand off now, before "
          "any new work.{digest} Rewrite the OPEN bucket's STATE.md as the handoff, by the task "
          "skill's STATE rules, in at most ~{lines} lines (sized to how full this session is){cite}"
          "; Next action exact; under User said, the user's own words "
          "quoted - every approval, preference, way they want results reported, worry and open "
          "question that lives only in this chat; paths, commands and IDs copied exactly; traps "
          "as seen, never inferred. If no bucket is open, open one the /task way and write it "
          "there - or, if nothing needs to carry over, skip the bucket and just tell the user to "
          "/clear. If work goes on after the handoff (a commit, a push), keep STATE.md current "
          "before each turn ends. Then tell the user in one line: handoff saved - run /clear, "
          "then type /continue.")
DIGEST_NOTE = (" The kit has written this conversation's digest - every user message and every "
               "answer verbatim, the tool trail without outputs, ~{k}K tokens - to `{path}`, "
               "and refreshes it after each later turn.")
DIGEST_CITE = ("; put `Digest: {path}` under ## Repo, and cite a digest turn (`digest T12`) "
               "instead of restating what it holds word for word")
# Not "saved": REASON lets the model skip the handoff when nothing carries over (code-review).
NOTICE = ("Context {pct}% full - handoff written? Next: /clear, then type /continue.")


def flag(name):
    return os.environ.get(name, "").strip().lower() in TRUTHY


def window(model):
    """The context window Claude Code gives `model`, from its id and the env it runs in.

    1M unless the model is one known to run 200K. The "[1m]" marker never reaches the
    transcript (the `model` attachment and message.model both drop it - measured 2.1.284 on a
    claude-opus-5-5[1m] session), so a 200K default read every new 1M model as 5x fuller than
    it was: Fable 5.1 on 2026-09-23, then Opus 5.5 on 2026-09-29 (32 false "45-99%" alarms at
    90-199K in 5 sessions). The rules are code.claude.com/docs/en/model-config: on the
    Anthropic API Fable, Sonnet 5+ and Opus 4.7+ run 1M with no [1m]; Haiku, Sonnet 4.x and
    Opus <= 4.6 run 200K unless [1m]; Bedrock / Vertex / Foundry run 200K unless [1m].
    """
    try:
        cap = int(os.environ.get("CLAUDE_CODE_MAX_CONTEXT_TOKENS") or 0)
    except ValueError:
        cap = 0
    # Honoured for a claude- id only together with DISABLE_COMPACT, as Claude Code does.
    if cap > 0 and (flag("DISABLE_COMPACT") or "claude" not in model):
        return cap
    if flag("CLAUDE_CODE_DISABLE_1M_CONTEXT"):
        return WINDOW
    if "[1m]" in model:
        return WINDOW_1M
    if any(flag(v) for v in ("CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
                             "CLAUDE_CODE_USE_FOUNDRY")):
        return WINDOW
    m = FAMILY.search(model)
    if "claude-3" in model or (m and (
            m.group(1) == "haiku"
            or (m.group(1) == "sonnet" and int(m.group(2)) < 5)
            or (m.group(1) == "opus" and (int(m.group(2)), int(m.group(3) or 0)) <= (4, 6)))):
        return WINDOW
    return WINDOW_1M


def usage(transcript_path, session_id=""):
    """(used tokens, window) from the transcript; unreadable or missing = (0, WINDOW).

    With a session_id, a line carrying another sessionId is not this session's and is skipped.
    """
    used, named, replied = 0, "", ""
    try:
        with open(transcript_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"usage"' not in line and '"modelId"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(obj, dict):
                    continue
                if session_id and obj.get("sessionId") not in (None, session_id):
                    continue
                if obj.get("type") == "assistant" and obj.get("isSidechain") is False:
                    msg = obj.get("message") or {}
                    u = msg.get("usage")
                    if isinstance(u, dict) and msg.get("model") != "<synthetic>":
                        n = sum(int(u.get(k) or 0) for k in (
                            "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
                        used = n or used
                        replied = str(msg.get("model") or replied)
                elif obj.get("type") == "attachment":
                    att = obj.get("attachment") or {}
                    if att.get("type") == "model":
                        named = str((att.get("identity") or {}).get("modelId") or named)
    except OSError:
        return 0, WINDOW
    # The last `model` attachment names the model; before ~2.1.268 none was written and the
    # replies' model is all there is. A session already past 200K can only be a 1M one.
    w = window(named or replied)
    return used, (WINDOW_1M if w == WINDOW and used > WINDOW else w)


def state_lines(pct):
    """STATE.md's line budget at a handoff, by how full the session is: the user asked for a
    handoff that grows with the session (2026-10-07), the ~60-line rule being the 45% size."""
    return 60 if pct < 60 else 80 if pct < 70 else 100 if pct < 80 else 120


def scratch_root(data):
    """The project root whose .claude/scratch holds the buckets: CLAUDE_PROJECT_DIR, else the
    payload cwd, the first that has one (as kit-session-start.py picks it); else the first of
    them that is a directory, where the handoff will open its bucket."""
    roots = [r for r in (os.environ.get("CLAUDE_PROJECT_DIR"), data.get("cwd")) if r]
    return next((r for r in roots if os.path.isdir(os.path.join(r, ".claude", "scratch"))),
                next((r for r in roots if os.path.isdir(r)), None))


def digest_path(root, sid):
    return os.path.join(root, ".claude", "scratch", "_sessions", UNSAFE.sub("_", sid) + ".md")


def write_digest(data, sid, pct, used, size):
    """(path, tokens) of this session's digest, written now; (None, 0) when it cannot be."""
    root = scratch_root(data)
    transcript = data.get("transcript_path") or ""
    if kit_digest is None or not (root and sid and os.path.isfile(transcript)):
        return None, 0
    path = digest_path(root, sid)
    meta = {"session": sid, "pct": pct, "used_k": used // 1000, "window_k": size // 1000}
    n = kit_digest.write(transcript, path, meta, kit_digest.cap_tokens(pct, size))
    return (path, n) if n >= 0 else (None, 0)


def refresh_digest(data, sid, pct, used, size):
    """After the handoff, keep the digest current to the last turn before /clear: rewrite it
    when the transcript is newer. Measured 0.2 s on a 32 MB transcript."""
    root = scratch_root(data)
    transcript = data.get("transcript_path") or ""
    if not (root and sid):
        return
    path = digest_path(root, sid)
    try:
        if os.path.getmtime(transcript) <= os.path.getmtime(path):
            return
    except OSError:
        return  # no digest yet for this session: only a block writes the first one
    write_digest(data, sid, pct, used, size)


def main():
    if kit_off():
        return
    try:
        # Explicit UTF-8, same as the other hooks: sys.stdin uses the locale codec (cp1252 on
        # Windows) while the payload leaves non-ASCII raw.
        data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except Exception:
        return
    if os.environ.get("CLAUDE_CODE_SESSION_ATTENDED") == "0":
        return
    # A running shell (a dev server, a watcher) does not mean the task is unfinished; anything
    # else, including an entry of unknown shape, does.
    if any(not isinstance(t, dict) or t.get("type") != "shell"
           for t in data.get("background_tasks") or []):
        return
    sid = str(data.get("session_id") or "")
    used, size = usage(data.get("transcript_path") or "", sid)
    pct = used * 100 // size
    marker = os.path.join(tempfile.gettempdir(), "kit-context-" + UNSAFE.sub("_", sid or "unknown"))
    if pct < THRESHOLD:
        try:
            os.remove(marker)
        except OSError:
            pass
        return
    band = (pct - THRESHOLD) // BAND
    try:
        with open(marker, encoding="utf-8") as f:
            stored = int(f.read().strip())
    except (OSError, ValueError):
        stored = -1
    # stop_hook_active = this stop follows our own block: the handoff was just written, so the
    # user is told once. Blocking again would loop.
    if data.get("stop_hook_active"):
        _try(refresh_digest, data, sid, pct, used, size)
        out = {"systemMessage": NOTICE.format(pct=pct)}
    elif band > stored:
        with open(marker, "w", encoding="utf-8") as f:
            f.write(str(band))
        # The digest is written before the block, so the reason can name it; a failure to
        # write it must not cost the handoff itself.
        path, k = _try(write_digest, data, sid, pct, used, size) or (None, 0)
        shown = path.replace("\\", "/") if path else ""
        out = {"decision": "block",
               "reason": REASON.format(
                   pct=pct, used=used // 1000, window=size // 1000, lines=state_lines(pct),
                   digest=DIGEST_NOTE.format(k=max(k // 1000, 1), path=shown) if path else "",
                   cite=DIGEST_CITE.format(path=shown) if path else "")}
    else:
        # Same band again: already said. A notice on every stop reached 56 in one session.
        _try(refresh_digest, data, sid, pct, used, size)
        return
    sys.stdout.write(json.dumps(out))


def _try(fn, *args):
    """fn(*args), or None when it raises: the digest is an extra, the block is the handoff."""
    try:
        return fn(*args)
    except Exception:
        return None


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        pass
