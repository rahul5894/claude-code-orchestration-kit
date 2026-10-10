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

The session digest (kit_digest.py: every user message and answer verbatim, the tool trail,
output excerpts; no model call) goes into the handoff's own bucket. The block writes nothing
and names no path; every stop after it finds the bucket whose STATE.md THIS session wrote last
(its own transcript says which) and keeps <bucket>/digests/<session>.md current, so it reaches
the last turn before /clear and /continue finds it beside the STATE.md it reads. REASON sizes STATE.md by the band
(kit_digest.BANDS: 60/80/100/120 lines). Measured 2026-10-07 on 4 real handoff chains: STATE.md
alone let a cold reader answer 63.4% of 80 probes, STATE.md + digest 94.7%; Claude Code's own
/compact 72.5% (bucket kit-2.1.292-optimize, F13).

Every stop - headless, or with an agent still running, too - first updates this session's entry
in its bucket's timeline (kit_chain.touch: <bucket>/digests/<sid>.json, the STATE snapshot,
SESSIONS.md; bucket handoff-timeline): a killed or closed window fires no SessionEnd, so the
entry has to exist before the session ends.

Exit 0 always. Any crash = silence (fail open, dev tool). Writes the temp-dir band marker, the
timeline entry and the digest only; neither of the last two failing ever costs the block.
Self-check: python kit-context_test.py
"""
import json
import os
import re
import sys

# The hook's own folder, explicitly: under PYTHONSAFEPATH=1 (or python -P / -I) the script dir
# is not on sys.path, the import fails and the hook exits 1 - which fails open (refuter-02).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_off import kit_off  # noqa: E402
from kit_index import MAX_TRANSCRIPT, context_marker, scratch_root, session_bucket  # noqa: E402
from kit_index import window as window_id  # noqa: E402

THRESHOLD = 45
BAND = 10
WINDOW = 200_000
WINDOW_1M = 1_000_000
UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
# family, major, minor of a Claude model id; a date (-20250514) or a -v1:0 suffix is no minor.
FAMILY = re.compile(r"claude-(opus|sonnet|haiku|fable)-(\d+)(?:-(\d{1,2}))?(?![0-9])")
TRUTHY = ("1", "true", "yes", "on")
REASON = ("orchestration-kit: context is at {pct}% ({used}K of {window}K). Hand off now, before "
          "any new work. {where} It is the handoff: write it by the task "
          "skill's STATE rules, in at most ~{lines} lines (sized to how full this session is). "
          "The kit then saves this whole conversation word for word into that bucket's digests/ "
          "and keeps it current each turn, and lists the session in the bucket's SESSIONS.md "
          "timeline (both written by the kit, never by you), so STATE.md is the curated "
          "snapshot, not a transcript"
          "; Next action exact; under User said, the user's own words "
          "quoted - every approval, preference, way they want results reported, worry and open "
          "question that lives only in this chat; paths, commands and IDs copied exactly; traps "
          "as seen, never inferred. If nothing needs to carry over, skip it and just tell the "
          "user to /clear. If work goes on after the handoff (a commit, a push), keep STATE.md current "
          "before each turn ends. Then tell the user in one line: handoff saved - run /clear, "
          "then type /continue.")
# Named from the session's own transcript: "the OPEN bucket" let a window with no bucket of its
# own hand off into a parallel window's (bucket parallel-window-resume, F5).
WHERE_MINE = "This session's bucket is `{slug}`: rewrite .claude/scratch/{slug}/STATE.md."
WHERE_NONE = ("This session has touched no bucket: open one for what this conversation did, the "
              "/task way, and write its STATE.md - never another task's bucket, which may be a "
              "parallel window's.")
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
    """STATE.md's line budget at a handoff: the user's table in kit_digest.BANDS (2026-10-07, a
    handoff that grows with the session); the ~60-line rule when the module is missing."""
    try:
        import kit_digest
        return kit_digest.budget(pct)[0]
    except Exception:
        return 60


# scratch_root, session_bucket and MAX_TRANSCRIPT live in kit_index.py: kit-session-start and
# kit-session-end use them too. The digest never creates .claude/scratch: a project with no
# bucket yet gets one from the handoff itself, and the next stop writes the digest.


def chain_touch(data, sid, pct, size):
    """This session's entry in each bucket it works on, after EVERY turn (kit_chain.touch):
    SessionEnd never fires for a killed or closed window, so the entry must already be there."""
    root = scratch_root(data)
    if root and sid:
        import kit_chain
        kit_chain.touch(data.get("transcript_path") or "", sid, root, pid=window_id(), pct=pct,
                        window_k=size // 1000)


def where(data):
    """Which STATE.md the handoff goes to: the bucket this session wrote or read last, by its
    own transcript; none touched = open a new one, never a parallel window's."""
    root = _try(scratch_root, data)
    bucket = _try(session_bucket, data.get("transcript_path") or "", root, True) if root else None
    return WHERE_MINE.format(slug=os.path.basename(bucket)) if bucket else WHERE_NONE


def sync_digest(data, sid, pct, used, size):
    """After the block, keep <bucket>/digests/<session>.md current to the last turn before
    /clear, in the bucket this session handed off to. Never through a symlinked or junctioned
    digests/ folder: write and prune would follow it out of the bucket (refuter 6)."""
    root = scratch_root(data)
    transcript = data.get("transcript_path") or ""
    if not (root and sid and os.path.isfile(transcript)) or os.path.getsize(transcript) > MAX_TRANSCRIPT:
        return
    bucket = session_bucket(transcript, root)
    if not bucket:
        return  # this session wrote no STATE.md: no handoff to sit beside
    folder = os.path.join(bucket, "digests")
    if os.path.lexists(folder) and (os.path.islink(folder)
                                    or os.path.realpath(folder) != os.path.join(os.path.realpath(bucket), "digests")):
        return
    path = os.path.join(folder, UNSAFE.sub("_", sid) + ".md")
    if os.path.isfile(path) and os.path.getmtime(transcript) <= os.path.getmtime(path):
        return
    import kit_digest
    meta = {"session": sid, "pct": pct, "used_k": used // 1000, "window_k": size // 1000}
    kit_digest.write(transcript, path, meta, kit_digest.cap_tokens(pct, size))


def main():
    if kit_off():
        return
    try:
        # Explicit UTF-8, same as the other hooks: sys.stdin uses the locale codec (cp1252 on
        # Windows) while the payload leaves non-ASCII raw.
        data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except Exception:
        return
    sid = str(data.get("session_id") or "")
    used, size = usage(data.get("transcript_path") or "", sid)
    pct = used * 100 // size
    # The timeline entry first: a headless session or one with an agent still running is still
    # a session that worked on its bucket (bucket handoff-timeline).
    _try(chain_touch, data, sid, pct, size)
    if os.environ.get("CLAUDE_CODE_SESSION_ATTENDED") == "0":
        return
    # A running shell (a dev server, a watcher) does not mean the task is unfinished; anything
    # else, including an entry of unknown shape, does.
    if any(not isinstance(t, dict) or t.get("type") != "shell"
           for t in data.get("background_tasks") or []):
        return
    marker = context_marker(sid)
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
    # stop_hook_active = this stop follows a block: the handoff was just written, so the user is
    # told once - unless no block of ours came first (another Stop hook blocked). Every stop
    # after our block keeps the digest current; a failure there never costs the notice.
    if data.get("stop_hook_active"):
        if stored < 0:
            return
        _try(sync_digest, data, sid, pct, used, size)
        out = {"systemMessage": NOTICE.format(pct=pct)}
    elif band > stored:
        # The block itself writes no digest: it stays as fast as before, and the digest goes
        # where the model puts the handoff, known once it has written STATE.md.
        with open(marker, "w", encoding="utf-8") as f:
            f.write(str(band))
        out = {"decision": "block",
               "reason": REASON.format(pct=pct, used=used // 1000, window=size // 1000,
                                       lines=state_lines(pct), where=where(data))}
    else:
        # Same band again: already said. A notice on every stop reached 56 in one session.
        _try(sync_digest, data, sid, pct, used, size)
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
