"""Per-task session timeline: every session that worked on a bucket leaves a record in it, and
SESSIONS.md lists those sessions in order (bucket handoff-timeline, D001-D004).

Inside .claude/scratch/<slug>/:
  digests/<sid>.json      the session's entry - written only by that session's own hooks, one
                          writer per file (Windows has no atomic append across processes)
  digests/<sid>.state.md  STATE.md as that session last wrote it: S1's handoff outlives S2's
  digests/<sid>.md        the verbatim digest (kit_digest.py), now for every session, at any %
  SESSIONS.md             a VIEW rendered from the entries - S1, S2... by first touch of the
                          bucket, ties by sid. Never edited by hand or by the model.

Who calls what: kit-context (Stop) -> touch() after every turn; kit-session-end (SessionEnd) ->
finish() = touch + digest; kit-session-start -> maintain(): finish one session that never got a
SessionEnd (a killed or closed window fires none, and the next window has another CLAUDE_PID),
prune, re-render a stale view.

Why: measured 2026-10-09 over 393 sessions - 55% of buckets span 2+ sessions (max 9, over 8
days); STATE.md is replaced at each handoff and only 5 digests were kept, so S1-S4 of a
9-session task were gone; 12 of 31 sessions that wrote a handoff had no digest (none was written
under 45%). Retention is the user's (2026-10-09): an OPEN bucket keeps everything; CLOSED <date>
+ 7 days deletes the verbatim records (digests/*.md), never the entries, SESSIONS.md, STATE.md,
DECISIONS.md or FINDINGS.md.

Not extracted, on purpose (D004): commits (375 of the user's 407 `git commit` calls are -q and
print no sha) and F/D ids from tool inputs (heredocs and subagents append too). FINDINGS ranges
come from line counts taken at each turn, D ids from the DECISIONS lines in that range.

    python kit_chain.py --backfill <project-root> [--transcripts <dir>] [--days 30]
"""
import hashlib
import json
import os
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kit_digest  # noqa: E402
from kit_index import (MAX_TRANSCRIPT, NOTE_PATH, SHELLS, WRITERS, alive, bucket_dir,  # noqa: E402
                       linked, read_window, safe_dir, scratch_ok, shell_notes)

SCRATCH_PATH = re.compile(r"\.claude[/\\]scratch[/\\]", re.IGNORECASE)
SLUG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
SID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
D_ID = re.compile(r"^\s*[-*]\s*\**(D\d{1,4})\b")
CLOSED_RE = re.compile(r"\bStatus\b[*:\s]{1,6}CLOSED\b[*\s]*(\d{4}-\d{2}-\d{2})?", re.IGNORECASE)
NEXT_HEAD = re.compile(r"^#{1,4}\s*Next action\b", re.IGNORECASE)
HEAD_LINE = re.compile(r"^\s*(?:#|<!--|$)")

# A snapshot reads exactly like a live STATE.md; in the step-back A/B (2026-10-09) every one of
# 10 confident wrong answers was an older session's fact taken over a newer one - an old
# snapshot's Next action among them. So each snapshot, and the view, says it is history.
SNAPSHOT_BANNER = ("<!-- HISTORY: STATE.md as session {sid} left it, {when}. Every later session and "
                   "the current STATE.md override it; never act on its Next action. -->\n")
KEEP_DAYS = 7                # the user's: verbatim records go 7 days after the bucket closes
SAY = 160                    # chars of asked / next / last said
FILES_SHOWN = 6
MAX_FILES = 40
MAX_ENTRIES = 500
MAX_ENTRY = 65_536
MAX_NOTE = 4_000_000         # FINDINGS.md / DECISIONS.md read cap, bytes
MAX_STATE = 200_000
STATE_SLACK = (-5, 600)      # STATE.md's mtime vs this session's last STATE write: same handoff
REPAIR_IDLE = 1800           # no window id: a transcript idle this long is a dead session
REPAIR_MIN_AGE = 60          # an entry touched this recently may still be mid-SessionEnd
REPAIR_MAX = 60_000_000      # bigger transcripts are repaired without a digest
TMP_STALE = 3600


def _try(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except Exception:
        return None


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError, OverflowError):
        return 0


def _epoch(ts):
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except (ValueError, OSError, OverflowError):
        return None


def _one(text, n=SAY):
    return kit_digest._one_line(kit_digest.redact(str(text)), n)


def _read(path, cap):
    """A regular file that is no link, decoded, at most `cap` bytes; None otherwise."""
    try:
        if linked(path) or not os.path.isfile(path):
            return None
        with open(path, "rb") as f:
            return f.read(cap).decode("utf-8", "replace")
    except OSError:
        return None


def _lines(path):
    text = _read(path, MAX_NOTE)
    return text.splitlines() if text is not None else []


def _load(path):
    text = _read(path, MAX_ENTRY)
    try:
        e = json.loads(text) if text else None
    except ValueError:
        return None
    ok = isinstance(e, dict) and isinstance(e.get("sid"), str) and isinstance(e.get("joined"), str)
    return e if ok else None


def _write_if_changed(path, text):
    if linked(path):
        return False
    if _read(path, len(text.encode("utf-8")) + 2) == text:
        return False
    kit_digest.write_atomic(path, text)
    return True


# ---------------------------------------------------------------- reading the session's transcript

def scan(transcript, sid=""):
    """One pass over the session's own main-chain lines (sidechains and lines of another
    sessionId - a fork's copied history - are skipped). Returns {first, last, users: [(line,
    text)], texts: [(line, text)], edits: [(line, path)], buckets: {slug: {joined, joined_line,
    last_line, last_ts, wrote_state, wrote_notes, read, state_ts, state_content}}}, or None when
    the transcript is unreadable or too big. Only lines that can matter are parsed: tool output
    (most of a transcript) never is."""
    try:
        if os.path.getsize(transcript) > MAX_TRANSCRIPT:
            return None
        f = open(transcript, encoding="utf-8", errors="replace")
    except (OSError, TypeError, ValueError):
        return None
    info = {"first": "", "last": "", "users": [], "texts": [], "edits": [], "buckets": {}}
    with f:
        for n, line in enumerate(f, 1):
            # Substring tests only, with no `:` spacing assumed: a format change must cost speed,
            # never silently drop lines.
            if '"isSidechain":true' in line or ('"tool_use"' not in line and (
                    '"tool_result"' in line or ('"user"' not in line and '"text"' not in line))):
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if (not isinstance(o, dict) or o.get("isSidechain") or o.get("type") not in ("user", "assistant")
                    or (sid and o.get("sessionId") not in (None, sid))):
                continue
            ts = str(o.get("timestamp") or "")
            if ts:
                info["first"] = info["first"] or ts
                info["last"] = ts
            msg = o.get("message") if isinstance(o.get("message"), dict) else {}
            content = msg.get("content")
            if o["type"] == "user":
                if o.get("isMeta") or o.get("isCompactSummary") or (isinstance(content, list) and any(
                        isinstance(b, dict) and b.get("type") == "tool_result" for b in content)):
                    continue
                text = kit_digest.clean_user(kit_digest._blocks_text(content))
                if text and not kit_digest.harness_text(text):  # a task notice is never `asked`
                    info["users"].append((n, text))
                continue
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and (b.get("text") or "").strip():
                    info["texts"].append((n, b["text"].strip()[:2000]))
                elif b.get("type") == "tool_use":
                    _tool(info, n, ts, b)
    return info


def _tool(info, n, ts, b):
    name = b.get("name") or ""
    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
    if name in WRITERS or name in ("Read", "NotebookEdit"):
        target, write = str(inp.get("file_path") or inp.get("notebook_path") or ""), name != "Read"
        if write and target and not SCRATCH_PATH.search(target):
            info["edits"].append((n, target))
        notes = [(m.group(1), m.group(2).upper(), write) for m in NOTE_PATH.finditer(target)]
    elif name in SHELLS:
        notes = shell_notes(inp.get("command"))  # written only where the note is the target
    else:
        return
    for slug, note, write in notes:
        v = info["buckets"].setdefault(slug, {
            "joined": ts, "joined_line": n, "wrote_state": False, "wrote_notes": False,
            "read": False, "state_ts": "", "state_content": None})
        v["last_line"], v["last_ts"] = n, ts
        if not write:
            v["read"] = True
        elif note == "STATE":
            v["wrote_state"], v["state_ts"] = True, ts
            content = inp.get("content") if name == "Write" else None
            v["state_content"] = content if isinstance(content, str) else None
        else:
            v["wrote_notes"] = True


def owned(info, root):
    """{slug: bucket dir} this session gets an entry in: every bucket whose STATE, FINDINGS or
    DECISIONS it wrote; none written = the one it read last (a /continue that has not handed off
    yet), as kit_index.session_bucket(reads=True) picks it."""
    b = {s: v for s, v in info["buckets"].items() if SLUG_RE.fullmatch(s) and not s.startswith("_")}
    wrote = [s for s, v in b.items() if v["wrote_state"] or v["wrote_notes"]]
    pick = wrote or ([max(b, key=lambda s: b[s]["last_line"])] if b else [])
    return {s: d for s in pick if (d := bucket_dir(root, s))}


def _typed(text):
    """A message in the user's own words: no slash command, or one given a sentence (`/continue
    kya hum in numbers ko...` - a common way to resume WITH a request). `/continue alpha` or a bare
    `/clear` is not; the 2026-10-10 session's asked came out as `/clear` before this."""
    return not text.startswith("/") or len(text.split()) >= 4


def _asked(users, upto, before=None):
    """The user's request: the first typed message (a bare slash command only when nothing else
    was typed); for a bucket the session moved to later, the last one typed before it did."""
    msgs = [(n, t) for n, t in users if upto is None or n <= upto]
    plain = [(n, t) for n, t in msgs if _typed(t)]
    if before is not None:
        prior = [t for n, t in plain if n <= before]
        if prior:
            return _one(prior[-1])
    if plain:
        return _one(plain[0][1])
    return _one(msgs[0][1]) if msgs else ""


def _next(state):
    """What sits under STATE.md's `## Next action`, up to the next heading, as one line (a
    "Offered and not done:" line is nothing without the list under it)."""
    lines = state.splitlines()
    for i, line in enumerate(lines):
        if NEXT_HEAD.match(line):
            got = []
            for x in lines[i + 1:]:
                s = x.strip()
                if s.startswith("#") or (not s and got):
                    break
                if s and not s.startswith("<!--"):
                    got.append(s.lstrip("-* ").strip())
                if len(" ".join(got)) > SAY:
                    break
            return _one(" ".join(got))
    return ""


def _state_then(bucket, v):
    """STATE.md as this session left it: the Write's own content when its last write was a
    Write; else the file, only while its mtime still matches this session's last write (a
    parallel window's later rewrite is never taken for this one's)."""
    if v.get("state_content") is not None:
        return v["state_content"]
    t0 = _epoch(v.get("state_ts"))
    path = os.path.join(bucket, "STATE.md")
    text = _read(path, MAX_STATE)
    try:
        fresh = t0 is not None and t0 + STATE_SLACK[0] <= os.path.getmtime(path) <= t0 + STATE_SLACK[1]
    except OSError:
        return None
    return text if fresh else None


def _rel(path, root):
    p = os.path.normpath(path)
    r = os.path.normpath(root)
    if os.path.normcase(p).startswith(os.path.normcase(r) + os.sep):
        p = p[len(r) + 1:]
    return p.replace("\\", "/")


# ---------------------------------------------------------------- writing the entry and the view

def touch(transcript, sid, root, pid="", pct=None, window_k=None, end=False, counts=True):
    """Upsert this session's entry in every bucket it owns (owned()); returns {info, mine, last}
    or {} when it owns none. A bucket it no longer owns (it read A, then wrote B) loses the
    entry it got for the read."""
    sid = UNSAFE.sub("_", str(sid or ""))
    if not (sid and transcript and scratch_ok(root)):
        return {}
    info = scan(transcript, sid)
    if not info or not info["buckets"]:
        return {}
    mine = owned(info, root)
    if not mine:
        return {}
    b = info["buckets"]
    last = max(mine, key=lambda s: b[s]["last_line"])
    first = min(mine, key=lambda s: b[s]["joined_line"])
    for slug, bucket in mine.items():
        _try(_upsert, bucket, slug, info, sid, root, transcript, pid, pct, window_k, end,
             None if slug == last else b[slug]["last_line"], slug == first, counts)
    for slug in b:
        if slug not in mine and (other := bucket_dir(root, slug)):
            _try(_drop, other, sid)
    return {"info": info, "mine": mine, "last": last}


def _upsert(bucket, slug, info, sid, root, transcript, pid, pct, window_k, end, upto, first, counts):
    folder = safe_dir(bucket, "digests")
    if not folder or not kit_digest.ensure_folder(folder):
        return
    path = os.path.join(folder, sid + ".json")
    old = _load(path) or {}
    v = info["buckets"][slug]
    last = (v["last_ts"] if upto else info["last"]) or v["last_ts"]
    texts = [t for n, t in info["texts"] if upto is None or n <= upto]
    seen, files = set(), []
    for n, p in info["edits"]:
        rel = _rel(p, root)
        if (upto is None or n <= upto) and os.path.normcase(rel) not in seen:
            seen.add(os.path.normcase(rel))
            files.append(rel)
    e = {"v": 1, "sid": sid, "slug": slug, "joined": v["joined"], "last": last, "end": None,
         "wrote_state": bool(v["wrote_state"] or old.get("wrote_state")),
         "asked": _asked(info["users"], upto, None if first else v["joined_line"]),
         "said": _one(texts[-1]) if texts else "", "next": old.get("next", ""),
         "files": files[:MAX_FILES], "pid": str(pid or old.get("pid") or ""), "transcript": transcript,
         "pct": pct if pct is not None else old.get("pct"),
         "window_k": window_k or old.get("window_k"),
         "lines": ({"FINDINGS": len(_lines(os.path.join(bucket, "FINDINGS.md"))),
                    "DECISIONS": len(_lines(os.path.join(bucket, "DECISIONS.md")))} if counts
                   else old.get("lines", {}))}
    # A resumed session that goes on past its end is open again until its next SessionEnd.
    e["end"] = last if end else (old.get("end") if (old.get("end") or "") >= last else None)
    if v["wrote_state"]:
        state = _state_then(bucket, v)
        if state:
            _write_if_changed(os.path.join(folder, sid + ".state.md"), SNAPSHOT_BANNER.format(
                sid=sid, when=kit_digest.local_time(v.get("state_ts") or last, "%Y-%m-%d %H:%M")) + state)
            e["next"] = _next(state) or e["next"]
    if _write_if_changed(path, json.dumps(e, ensure_ascii=False, indent=1) + "\n") or not os.path.isfile(
            os.path.join(bucket, "SESSIONS.md")):
        render(bucket)


def _drop(bucket, sid):
    folder = safe_dir(bucket, "digests")
    path = os.path.join(folder, sid + ".json") if folder else ""
    e = _load(path) if path else None
    if e and not e.get("wrote_state"):
        os.remove(path)
        render(bucket)


def _entries(bucket):
    folder = safe_dir(bucket, "digests")
    try:
        names = sorted(f for f in os.listdir(folder) if f.endswith(".json")) if folder else []
    except OSError:
        return folder, []
    out = [e for e in (_load(os.path.join(folder, f)) for f in names[:MAX_ENTRIES]) if e]
    return folder, sorted(out, key=lambda e: (e.get("joined") or "", e["sid"]))


def _span(e):
    a = e.get("joined") or ""
    b = e.get("end") or e.get("last") or a
    day = kit_digest.local_time(a, "%m-%d")
    tail = kit_digest.local_time(b, "%H:%M" if kit_digest.local_time(b, "%m-%d") == day else "%m-%d %H:%M")
    return f"{day} {kit_digest.local_time(a)}→{tail}"


def _head(lines):
    n = 0
    while n < len(lines) and HEAD_LINE.match(lines[n]):
        n += 1
    return n


def render(bucket):
    """SESSIONS.md from the entries: ~3 lines a session, oldest first. Rewritten only when it
    changes; a linked SESSIONS.md is never written through. A FINDINGS range is the lines added
    between the previous session's last turn and this one's: exact for sessions one after
    another, approximate for two that overlap (∥) on the same bucket."""
    folder, entries = _entries(bucket)
    if not entries and not os.path.isfile(os.path.join(bucket, "SESSIONS.md")):
        return
    findings = _lines(os.path.join(bucket, "FINDINGS.md"))
    decisions = _lines(os.path.join(bucket, "DECISIONS.md"))
    f_prev, d_prev = _head(findings), _head(decisions)
    spans = [(_epoch(e.get("joined")) or 0, _epoch(e.get("end") or e.get("last")) or 0) for e in entries]
    out = [f"# SESSIONS — {os.path.basename(bucket)}",
           "<!-- Written by the kit from digests/<sid>.json - never edit. Oldest first; times local "
           f"(UTC{time.strftime('%z')}). S<n> is display order: cite a session by its sid. Per session: "
           "digests/<sid>.md = what was said, verbatim; digests/<sid>.state.md = STATE.md as it "
           "left it. -->",
           "History, oldest first: a later session overrides an earlier one, and `next then` was "
           "that session's next step - the current one is in STATE.md."]
    for i, e in enumerate(entries):
        a, b = spans[i]
        flags = ["STATE written" if e.get("wrote_state") else "no STATE write"]
        par = [f"S{j + 1}" for j, (x, y) in enumerate(spans) if j != i and x < b and a < y]
        if par:
            flags.append("∥ " + ",".join(par))
        if not os.path.isfile(os.path.join(folder, e["sid"] + ".md")):
            flags.append("no verbatim record")
        if not e.get("end"):
            flags.append("not ended")
        out.append(f"## S{i + 1} · {e['sid']} · {_span(e)} · " + " · ".join(flags))
        if e.get("asked"):
            out.append(f'asked: "{e["asked"]}"')
        if e.get("next"):
            out.append("next then: " + e["next"])
        elif e.get("said"):
            out.append("last said: " + e["said"])
        tail = []
        files = e.get("files") or []
        if files:
            tail.append("files: " + ", ".join(f"`{p}`" for p in files[:FILES_SHOWN])
                        + (f" (+{len(files) - FILES_SHOWN})" if len(files) > FILES_SHOWN else ""))
        lines = e.get("lines") if isinstance(e.get("lines"), dict) else {}
        fl = min(_int(lines.get("FINDINGS")), len(findings))
        if fl > f_prev:
            tail.append(f"FINDINGS L{f_prev + 1}-{fl}")
            f_prev = fl
        dl = min(_int(lines.get("DECISIONS")), len(decisions))
        if dl > d_prev:
            ids = [m.group(1) for x in decisions[d_prev:dl] if (m := D_ID.match(x))]
            tail.append(", ".join(dict.fromkeys(ids)) if ids else f"DECISIONS L{d_prev + 1}-{dl}")
            d_prev = dl
        if tail:
            out.append(" · ".join(tail))
    _write_if_changed(os.path.join(bucket, "SESSIONS.md"), "\n".join(out) + "\n")


# ---------------------------------------------------------------- the session's end

def _cut_turns(turns, upto):
    """The turns up to transcript line `upto`, the last one trimmed there: a bucket the session
    left gets the talk about it, never the next task's."""
    out = []
    for t in turns:
        if t["line"] > upto:
            break
        items = [it for it in t["items"] if it[2] <= upto]
        out.append(dict(t, items=items, outs={k: v for k, v in t["outs"].items() if k < len(items)}))
    return out


def finish(transcript, sid, root, pid="", deadline=None, digest=True, counts=True):
    """touch(end=True), then the verbatim digest in every bucket the session owns (the one it
    touched last first: /continue reads that), unless one already newer than the transcript is
    there (kit-context keeps it current past 45%). Returns how many digests it wrote."""
    t = touch(transcript, sid, root, pid=pid, end=True, counts=counts)
    if not t or not digest:
        return 0
    sid = UNSAFE.sub("_", str(sid))
    turns, wrote = None, 0
    for slug in sorted(t["mine"], key=lambda s: s != t["last"]):
        if deadline and time.time() > deadline:
            break
        bucket = t["mine"][slug]
        folder = safe_dir(bucket, "digests")
        if not folder:
            continue
        out = os.path.join(folder, sid + ".md")
        try:
            if os.path.isfile(out) and os.path.getmtime(out) >= os.path.getmtime(transcript):
                continue
        except OSError:
            continue
        if turns is None:
            turns = kit_digest.extract(transcript)
        part = turns if slug == t["last"] else _cut_turns(turns, t["info"]["buckets"][slug]["last_line"])
        e = _load(os.path.join(folder, sid + ".json")) or {}
        pct, wk = _int(e.get("pct")), _int(e.get("window_k")) or 1000
        meta = {"session": sid, "pct": pct or "?", "used_k": pct * wk // 100 if pct else "?", "window_k": wk}
        if kit_digest.write(transcript, out, meta, kit_digest.cap_tokens(pct, wk * 1000), turns=part) > 0:
            wrote += 1
            render(bucket)
    return wrote


# ---------------------------------------------------------------- repair, retention, upkeep

def _buckets(root, closed=False):
    """Bucket folders under a safe scratch (and its _closed/ with closed=True), none linked."""
    if not scratch_ok(root):
        return []
    scratch = os.path.join(root, ".claude", "scratch")
    bases = [scratch]
    if closed and os.path.isdir(os.path.join(scratch, "_closed")) and not linked(os.path.join(scratch, "_closed")):
        bases.append(os.path.join(scratch, "_closed"))
    out = []
    for base in bases:
        try:
            names = sorted(os.listdir(base))
        except OSError:
            continue
        for name in names:
            p = os.path.join(base, name)
            if SLUG_RE.fullmatch(name) and not name.startswith("_") and os.path.isdir(p) and not linked(p):
                out.append(p)
    return out


def _transcript_ok(path, sid):
    """A path read from a repo file names a Claude Code transcript only: `<uuid>.jsonl` under
    the config dir's projects/. A cloned repo's entry could otherwise point the repair at any
    file - another project's transcript digested into this repo."""
    if not (isinstance(path, str) and SID_RE.fullmatch(str(sid or ""))
            and os.path.basename(path) == sid + ".jsonl"):
        return False
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    try:
        projects = os.path.normcase(os.path.realpath(os.path.join(base, "projects")))
        real = os.path.normcase(os.path.realpath(path))
    except (OSError, ValueError):
        return False
    return real.startswith(projects + os.sep) and os.path.isfile(real)


def _due(e):
    """An unfinished entry whose session is over: its window process is gone, or that window
    has moved on to another session; with no window id, its transcript has been idle 30 min."""
    pid = str(e.get("pid") or "")
    if pid.isdigit():
        return not alive(pid) or read_window(pid).get("sid") != e["sid"]
    try:
        return time.time() - os.path.getmtime(e.get("transcript") or "") > REPAIR_IDLE
    except (OSError, ValueError):
        return False


def repair(root, skip=(), deadline=None):
    """Finish at most ONE session that ended with no SessionEnd. Never one in `skip` (this
    window's previous session: its SessionEnd may still be running, ~80 ms apart) nor an entry
    touched under a minute ago. Returns the sid repaired, or None."""
    seen = set(skip)
    for bucket in _buckets(root):
        folder, entries = _entries(bucket)
        for e in entries:
            sid = e["sid"]
            if e.get("end") or sid in seen:
                continue
            seen.add(sid)
            try:
                if time.time() - os.path.getmtime(os.path.join(folder, sid + ".json")) < REPAIR_MIN_AGE:
                    continue
            except OSError:
                continue
            if not _due(e) or not _transcript_ok(e.get("transcript"), sid):
                continue
            if deadline and time.time() > deadline:
                return None
            big = os.path.getsize(e["transcript"]) > REPAIR_MAX
            finish(e["transcript"], sid, root, pid=e.get("pid", ""), deadline=deadline, digest=not big)
            return sid
    return None


def _closed_at(bucket):
    """When the bucket closed - the end of the day its STATE.md's `Status: CLOSED <date>` names,
    else STATE.md's mtime; None while it is open."""
    path = os.path.join(bucket, "STATE.md")
    m = CLOSED_RE.search(_read(path, 2048) or "")
    if not m:
        return None
    if m.group(1):
        try:
            return time.mktime(time.strptime(m.group(1), "%Y-%m-%d")) + 86400
        except (ValueError, OverflowError):
            pass
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def prune(root, now=None):
    """The user's retention: a bucket closed more than KEEP_DAYS days ago loses its verbatim
    records (digests/*.md, which includes the *.state.md snapshots); its entries and SESSIONS.md
    stay. An open bucket loses nothing. Leftover *.tmp older than an hour go anywhere. Returns
    how many files it deleted."""
    now = now or time.time()
    gone = 0
    for bucket in _buckets(root, closed=True):
        folder = safe_dir(bucket, "digests")
        if not folder or not os.path.isdir(folder):
            continue
        closed = _closed_at(bucket)
        old = closed is not None and now - closed > KEEP_DAYS * 86400
        before = gone
        for name in os.listdir(folder):
            p = os.path.join(folder, name)
            try:
                if linked(p) or not os.path.isfile(p):
                    continue
                if (name.endswith(".tmp") and now - os.path.getmtime(p) > TMP_STALE) or (old and name.endswith(".md")):
                    os.remove(p)
                    gone += 1
            except OSError:
                pass
        if gone > before:
            _try(render, bucket)
    return gone


def maintain(root, skip=(), deadline=None):
    """SessionStart upkeep within `deadline`: repair one unfinished session, prune once a day
    per project, re-render a SESSIONS.md older than its entries."""
    if not scratch_ok(root):
        return
    deadline = deadline or time.time() + 2
    _try(repair, root, skip, deadline)
    key = hashlib.sha1(os.path.normcase(os.path.realpath(root)).encode("utf-8", "replace")).hexdigest()[:12]
    marker = os.path.join(tempfile.gettempdir(), f"kit-chain-prune-{key}")
    today = time.strftime("%Y-%m-%d")
    if _read(marker, 64) != today and time.time() < deadline:
        _try(prune, root)
        _try(kit_digest.write_atomic, marker, today)
    for bucket in _buckets(root):
        if time.time() > deadline:
            break
        folder = os.path.join(bucket, "digests")
        try:
            newest = max(os.path.getmtime(os.path.join(folder, f)) for f in os.listdir(folder) if f.endswith(".json"))
        except (OSError, ValueError):
            continue
        try:
            view = os.path.getmtime(os.path.join(bucket, "SESSIONS.md"))
        except OSError:
            view = 0
        if newest > view:
            _try(render, bucket)


# ---------------------------------------------------------------- one-off backfill

def project_folder(root, base=None):
    """Claude Code's transcript folder for `root`: every non-alphanumeric character -> '-'."""
    base = base or os.path.join(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude"), "projects")
    want = re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(root)).lower()
    try:
        return next((os.path.join(base, d) for d in os.listdir(base) if d.lower() == want), None)
    except OSError:
        return None


def backfill(root, transcripts=None, days=30, quiet_s=600):
    """Records for the buckets of `root` from transcripts still on disk (Claude Code keeps them
    30 days): every session that touched a bucket gets its entry and digest. Line counts are not
    taken (today's counts would be wrong for past sessions); a session still running (written in
    the last `quiet_s` seconds) is left to its own hooks. Returns the sessions recorded."""
    folder = transcripts or project_folder(root)
    if not folder or not scratch_ok(root):
        return 0
    since = time.time() - days * 86400
    done = 0
    for name in sorted(os.listdir(folder)):
        path = os.path.join(folder, name)
        if not name.endswith(".jsonl") or not os.path.isfile(path):
            continue
        mt = os.path.getmtime(path)
        if mt < since or time.time() - mt < quiet_s:
            continue
        sid = name[:-len(".jsonl")]
        info = scan(path, sid)
        if info and owned(info, root):
            finish(path, sid, root, counts=False)
            done += 1
    return done


def main(argv):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", metavar="ROOT", required=True)
    ap.add_argument("--transcripts", help="transcript folder; default: this project's under ~/.claude/projects")
    ap.add_argument("--days", type=int, default=30)
    a = ap.parse_args(argv)
    n = backfill(a.backfill, a.transcripts, a.days)
    print(f"kit_chain: recorded {n} session(s) in {a.backfill}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
