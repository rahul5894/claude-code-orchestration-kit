"""Stop + PostToolBatch hook: at 45% context the session hands off and the user is told to /clear.

PostToolBatch (after each batch of tool calls, the main session's only - a payload with agent_id
is a subagent's) gives the model STEP_REASON as additionalContext the first time a band is
crossed mid-turn, and the band marker keeps the transcript's size at that moment. The Stop that
ends the turn then checks: a STATE.md written since = the user is told (NOTICE); none = the
usual block. Stop alone used to see only finished turns (bucket kit-optimize-pass D001).

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

The session digest (kit_digest.py: every user message and answer verbatim; the tool trail and
output excerpts beside it in <session>.tools.md; no model call) goes into the handoff's own bucket. The block writes nothing
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
import os
import sys

# The hook's own folder, explicitly: under PYTHONSAFEPATH=1 (or python -P / -I) the script dir
# is not on sys.path, the import fails and the hook exits 1 - which fails open (refuter-02).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_off import kit_off  # noqa: E402

if __name__ == "__main__" and kit_off():
    sys.exit(0)  # off here, the default: out before the imports below (kit-default-off-optimize D003)

import json  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402

from kit_index import (MAX_TRANSCRIPT, context_marker, keep, read_state, records_project, resumed,  # noqa: E402
                       scratch_root, session_bucket, session_root, shell_notes, write_atomic)
from kit_index import window as window_id  # noqa: E402

THRESHOLD = 45
BAND = 10
DIGEST_EVERY_S = 300  # past the handoff, one digest rebuild per 5 minutes at most (D005)
WINDOW = 200_000
WINDOW_1M = 1_000_000
UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
# family, major, minor of a Claude model id; a date (-20250514) or a -v1:0 suffix is no minor.
FAMILY = re.compile(r"claude-(opus|sonnet|haiku|fable)-(\d+)(?:-(\d{1,2}))?(?![0-9])")
TRUTHY = ("1", "true", "yes", "on")
# The rules' path, named: a session that never ran /task or /continue (a records project starts
# from "next item") looked for skills/task/SKILL.md and then ran `find /` over the whole disk,
# 2 of 2 live runs (bucket kit-records-integration, T14on); install.ps1 copies it there. Told
# "section 4" alone, 2 of 2 runs wrote STATE.md and no INDEX.md row (T15on), so both are named.
HEAD = ("orchestration-kit: context is at {pct}% ({used}K of {window}K). Hand off now, before "
        "any new work. ")
# Mid-turn (PostToolBatch, bucket kit-optimize-pass D001): Stop runs only when a turn ends, and a
# long turn crossed the bands silently - of 70 real sessions with a block the first came at 60%+
# in 20, and one turn went 45% -> 96% and auto-compacted with no alert at all (842 tool calls,
# qartez-mcp, 2026-10-10). A block here would stop the agentic loop until the user speaks, so the
# same handoff goes in as context, and the Stop that ends the turn is the backstop.
STEP_HEAD = ("orchestration-kit: context is at {pct}% ({used}K of {window}K), in the middle of "
             "this turn. Finish the step you are on, start nothing new, then hand off. ")
REASON = HEAD + (
          "{where} It is the handoff: write it by the task "
          "skill's STATE rules (~/.claude/commands/task.md, sections 1 and 4: the bucket's "
          "INDEX.md row and its STATE.md - read that file, never search for it), in at most "
          "~{lines} lines (sized to how full this session is). "
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
WHERE_MINE = ("This session's bucket is `{slug}`: update .claude/scratch/{slug}/STATE.md - change only "
              "what changed, every line still true kept word for word.")
WHERE_NONE = ("This session has touched no bucket: open one for what this conversation did, the "
              "/task way, and write its STATE.md - never another task's bucket, which may be a "
              "parallel window's.")
# A project-records project (bucket kit-records-integration): its record has session-end duties
# of its own, and a /clear right after the handoff would skip them - so the handoff asks for them
# too, and STATE.md names their ids instead of repeating them.
RECORDS_HANDOFF = (" This project keeps project-records: with the handoff, its own session-end entries as its "
                   "standing orders say - a docs/PROGRESS.md entry and a true Now line in docs/TIMELINE.md - "
                   "and any decision, finding or work item still only in this chat filed in docs/ first; "
                   "STATE.md names their ids and never repeats them.")
# Not "saved": REASON lets the model skip the handoff when nothing carries over (code-review).
NOTICE = ("Context {pct}% full - handoff written? Next: /clear, then type /continue.")
STEP_REASON = STEP_HEAD + REASON[len(HEAD):]
WRITE_TOOLS = ("Write", "Edit", "MultiEdit")


def flag(name):
    return os.environ.get(name, "").strip().lower() in TRUTHY


def window(model):
    """The window the 45% alert counts against: the model's (model_window), or the auto-compact
    window when one is set lower - compaction runs there, so counting against the model's window
    would let it compact before the alert ever fired (code.claude.com/docs/en/model-config)."""
    base = model_window(model)
    ac = auto_compact(base, model)
    return min(base, ac) if ac else base


def _tokens(v):
    """A window as /autocompact takes one: 200000, "500k", "1M" or a bare 100-1000 = thousands;
    0 when it is none of those or outside 100K-1M."""
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([km]?)", str(v).strip().lower())
    if not m:
        return 0
    n = float(m.group(1)) * {"k": 1_000, "m": 1_000_000}.get(m.group(2), 1)
    n = n * 1000 if not m.group(2) and 100 <= n <= 1000 else n
    return int(n) if 100_000 <= n <= 1_000_000 else 0


def auto_compact(base, model):
    """The auto-compact window this session runs with, 0 when none is set: the env var
    CLAUDE_CODE_AUTO_COMPACT_WINDOW (a plain token count; it beats everything), else the smallest
    `autoCompactWindow` of the user, project and local settings - per model in modelSettings, as
    /autocompact saves it since 2.1.288, before the file's top-level key. A session started with
    `--autocompact` is not visible here. CLAUDE_AUTOCOMPACT_PCT_OVERRIDE (1-99) lowers the point
    further, also on the model's own window."""
    # Read as Claude Code reads it: its leading digits, clamped to 100K-1M ("500k" is 500 -> 100K).
    env = re.match(r"\s*(\d+)", os.environ.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW", ""))
    win = min(max(int(env.group(1)), 100_000), 1_000_000) if env else 0
    if not win:
        root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        found = []
        for p in (os.path.join(os.path.expanduser("~"), ".claude", "settings.json"),
                  os.path.join(root, ".claude", "settings.json"),
                  os.path.join(root, ".claude", "settings.local.json")):
            try:
                with open(p, encoding="utf-8") as f:
                    s = json.load(f)
            except (OSError, ValueError):
                continue
            if not isinstance(s, dict):
                continue
            ms = s.get("modelSettings") if isinstance(s.get("modelSettings"), dict) else {}
            per = next((v.get("autoCompactWindow") for k, v in ms.items()
                        if k and isinstance(v, dict) and k in model), None)
            n = _tokens(per) if per is not None else 0
            n = n or _tokens(s.get("autoCompactWindow", ""))
            if n:
                found.append(n)
        win = min(found) if found else 0
    try:
        pct = int(os.environ.get("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE") or 0)
    except ValueError:
        pct = 0
    if 0 < pct < 100:
        win = (win or base) * pct // 100
    return win


def model_window(model):
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


def usage(transcript_path, session_id="", cache=None):
    """(used tokens, window) from the transcript; unreadable or missing = (0, WINDOW).

    With a session_id, a line carrying another sessionId is not this session's and is skipped.
    With `cache` (every Stop) it goes on from the state the last call kept (kit_index.resumed):
    only the lines appended since are read, a line still being written is left for the next call.
    """
    try:
        with open(transcript_path, "rb") as f:
            st = resumed(cache, f, {"transcript": transcript_path, "sid": session_id},
                         {"used": 0, "named": "", "replied": ""})
            for raw in f:
                if cache and not raw.endswith(b"\n"):
                    break
                st["offset"] += len(raw)
                if b'"usage"' not in raw and b'"modelId"' not in raw:
                    continue
                try:
                    obj = json.loads(raw.decode("utf-8", "replace"))
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
                        st["used"] = n or st["used"]
                        st["replied"] = str(msg.get("model") or st["replied"])
                elif obj.get("type") == "attachment":
                    att = obj.get("attachment") or {}
                    if att.get("type") == "model":
                        st["named"] = str((att.get("identity") or {}).get("modelId") or st["named"])
    except (OSError, TypeError, ValueError):
        return 0, WINDOW
    if cache:
        _try(keep, cache, st)
    used, named, replied = st["used"], st["named"], st["replied"]
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
    root = session_root(data)  # a session of no task goes in the session log (kit_chain.touch)
    if root and sid:
        import kit_chain
        kit_chain.touch(data.get("transcript_path") or "", sid, root, pid=window_id(), pct=pct,
                        window_k=size // 1000, cache=read_state(sid, ".scan"))


def where(data):
    """Which STATE.md the handoff goes to: the bucket this session wrote or read last, by its
    own transcript; none touched = open a new one, never a parallel window's."""
    root = _try(scratch_root, data)
    bucket = _try(session_bucket, data.get("transcript_path") or "", root, True) if root else None
    return WHERE_MINE.format(slug=os.path.basename(bucket)) if bucket else WHERE_NONE


def sync_digest(data, sid, pct, used, size, every=0):
    """After the block, keep <bucket>/digests/<session>.md current to the last turn before
    /clear, in the bucket this session handed off to. Never through a symlinked or junctioned
    digests/ folder: write and prune would follow it out of the bucket (refuter 6). `every`: at
    most one rebuild per that many seconds (D005) - each reads the whole transcript (30-120 ms),
    and SessionEnd writes the digest whole anyway (a killed window's: the next start's repair)."""
    stamp = read_state(sid, ".digest")
    if every and os.path.isfile(stamp) and time.time() - os.path.getmtime(stamp) < every:
        return
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
    write_atomic(stamp, "")


def read_marker(marker):
    """(band, offset): the band last said, and - when it was said mid-turn - the transcript's
    size at that moment; nothing said = (-1, None). A band alone is the Stop's own block."""
    try:
        with open(marker, encoding="utf-8") as f:
            band, _, at = f.read().strip().partition(":")
        return int(band), (int(at) if at else None)
    except (OSError, ValueError):
        return -1, None


def wrote_state_since(data, offset):
    """Did this session write a bucket's STATE.md after byte `offset` of its transcript: a
    Write/Edit/MultiEdit on it, or a shell command whose write target it is (kit_index.shell_notes)?"""
    transcript = data.get("transcript_path") or ""
    root = scratch_root(data)
    with open(transcript, "rb") as f:
        f.seek(offset)
        for raw in f:
            if b"STATE.md" not in raw or b'"tool_use"' not in raw:
                continue
            try:
                obj = json.loads(raw.decode("utf-8", "replace"))
            except ValueError:
                continue
            if not isinstance(obj, dict) or obj.get("type") != "assistant" or obj.get("isSidechain"):
                continue
            for b in (obj.get("message") or {}).get("content") or []:
                if not isinstance(b, dict) or b.get("type") != "tool_use":
                    continue
                inp = b.get("input") or {}
                path = str(inp.get("file_path") or "").replace("\\", "/")
                if b.get("name") in WRITE_TOOLS and path.endswith("/STATE.md") and "/.claude/scratch/" in path:
                    return True
                if b.get("name") in ("Bash", "PowerShell") and root and any(
                        note == "STATE" and written for _, note, written in shell_notes(inp.get("command"), root)):
                    return True
    return False


def main():
    try:
        # Explicit UTF-8, same as the other hooks: sys.stdin uses the locale codec (cp1252 on
        # Windows) while the payload leaves non-ASCII raw.
        data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except Exception:
        return
    sid = str(data.get("session_id") or "")
    step = data.get("hook_event_name") == "PostToolBatch"
    if step and data.get("agent_id"):
        return  # a subagent's own batch: its context is not this session's
    transcript = data.get("transcript_path") or ""
    used, size = usage(transcript, sid, read_state(sid, ".usage") if sid else None)
    pct = used * 100 // size
    if not step:
        # The timeline entry first: a headless session or one with an agent still running is
        # still a session that worked on its bucket (bucket handoff-timeline). Stop only: a
        # batch comes many times a turn, and the turn's Stop makes the entry.
        _try(chain_touch, data, sid, pct, size)
    if os.environ.get("CLAUDE_CODE_SESSION_ATTENDED") == "0":
        return
    # A running shell (a dev server, a watcher) does not mean the task is unfinished; anything
    # else, including an entry of unknown shape, does - at Stop. Mid-turn the notice still goes:
    # a session that always had an agent out was never told at all (qartez-mcp, 2026-10-10).
    if not step and any(not isinstance(t, dict) or t.get("type") != "shell"
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
    stored, said_at = read_marker(marker)
    fmt = dict(pct=pct, used=used // 1000, window=size // 1000, lines=state_lines(pct))
    if step:
        if band > stored:
            # Where in the transcript it was said: the Stop then knows whether a handoff followed.
            write_atomic(marker, f"{band}:{os.path.getsize(transcript) if os.path.isfile(transcript) else 0}")
            text = (STEP_REASON.format(where=where(data), **fmt)
                    + (RECORDS_HANDOFF if _try(records_project, _try(session_root, data)) else ""))
            sys.stdout.write(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolBatch",
                                                                 "additionalContext": text}}))
        return
    # stop_hook_active = this stop follows a block: the handoff was just written, so the user is
    # told once - unless no block of ours came first (another Stop hook blocked). Every stop
    # after our block keeps the digest current; a failure there never costs the notice.
    if data.get("stop_hook_active"):
        if stored < 0:
            return
        _try(sync_digest, data, sid, pct, used, size)
        out = {"systemMessage": NOTICE.format(pct=pct)}
    elif band > stored or (said_at is not None and not _try(wrote_state_since, data, said_at)):
        # A band said mid-turn and no STATE.md written since: the turn's end asks as before. The
        # block itself writes no digest: it stays as fast as before, and the digest goes where
        # the model puts the handoff, known once it has written STATE.md.
        write_atomic(marker, str(band))
        out = {"decision": "block",
               "reason": REASON.format(where=where(data), **fmt)
               + (RECORDS_HANDOFF if _try(records_project, _try(session_root, data)) else "")}
    elif said_at is not None:
        # The handoff was written mid-turn: the user is told once, as after a block.
        write_atomic(marker, str(band))
        _try(sync_digest, data, sid, pct, used, size)
        out = {"systemMessage": NOTICE.format(pct=pct)}
    else:
        # Same band again: already said. A notice on every stop reached 56 in one session.
        _try(sync_digest, data, sid, pct, used, size, DIGEST_EVERY_S)
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
