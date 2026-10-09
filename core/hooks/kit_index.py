"""The open rows of a task-bucket index, `.claude/scratch/INDEX.md`, for the two hooks that read
it (kit-session-start lists them and hands over STATE.md; kit-subagent-start injects DECISIONS.md),
so both agree on what is open.

Two shapes are read, because models write both: the /task table (`| slug | status | updated |
next action |`) and a bullet list (`- slug — STATUS — next`). Measured 2026-09-29: Strem-setup's
INDEX is bullets, and the table-only reader saw none of its 3 open buckets. OPEN and BLOCKED rows
of the table count as before. Any other open-sounding status (`IN PROGRESS` was skipped) and any
bullet row count only when the bucket folder exists: a legend table (`| OPEN | active |`) or a
prose bullet must not become a bucket. Callers still validate the slug before any path.

Below open_rows: which bucket a session works on (its own transcript says so) and which bucket
each Claude Code WINDOW is on, so two windows that both hand off and /clear each resume their own
task (bucket parallel-window-resume, D001). A window is the env `CLAUDE_PID`: measured on 2.1.294
it is the same before and after /clear and differs per window; documented since (env-vars page:
Claude Code's own process id in hook and shell subprocesses, v2.1.214+). Without it there is
simply no lineage and /continue asks when 2+ handoffs are free.

Also here, for every hook that writes into a bucket (kit-context, kit-session-end, kit_chain):
scratch_root() picks the project whose .claude/scratch holds the buckets, scratch_ok() refuses
a .claude or scratch that is a link or junction - a cloned repo could commit one pointing
anywhere, and a realpath check against the link's own target passes it (bucket
handoff-timeline, review) - and safe_dir() refuses a linked folder inside a bucket."""
import glob
import json
import os
import re
import tempfile
import time

from kit_off import kit_off

CELL_RE = re.compile(r"(?<!\\)\|")
BULLET_RE = re.compile(r"[-*]\s+(\S+?)\s+[—–-]{1,2}\s+(.+?)(?:\s+[—–-]{1,2}\s+(.*))?")
OPEN = ("OPEN", "BLOCKED")
OPEN_IF_FOLDER = ("IN PROGRESS", "IN-PROGRESS", "WIP", "ACTIVE", "ONGOING", "PAUSED", "WAITING",
                  "PENDING", "STARTED", "TODO")


def open_rows(index_path):
    """(slug, status, next action) for every open row, in file order. Unreadable = []."""
    scratch = os.path.dirname(index_path)
    try:
        with open(index_path, encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        s = line.strip()
        table = s.startswith("|")
        if table:
            cells = [c.strip() for c in CELL_RE.split(s.strip("|"))]
            if len(cells) < 2:
                continue
            slug, status, nxt = cells[0], cells[1], cells[3] if len(cells) >= 4 else ""
        else:
            m = BULLET_RE.fullmatch(s)
            if not m:
                continue
            slug, status, nxt = m.group(1), m.group(2), m.group(3) or ""
        slug = slug.strip("*` ")
        word = status.strip("*` ").upper()
        if not slug or not word.startswith(OPEN + OPEN_IF_FOLDER):
            continue
        if (not table or not word.startswith(OPEN)) and not os.path.isdir(os.path.join(scratch, slug)):
            continue
        out.append((slug, status.strip(), nxt.strip()))
    return out


# A touch of .claude/scratch/<slug>/STATE.md, in a Read/Write/Edit target or a shell command.
STATE_PATH = re.compile(r"(?:^|[/\\\s\"'=])\.claude[/\\]scratch[/\\]([^/\\\s\"'*?<>|]+)[/\\]STATE\.md",
                        re.IGNORECASE)
SHELL_WRITE = re.compile(r">|\btee\b|Set-Content|Out-File|Add-Content|write_text|\.write\(|"
                         r"open\([^)]*['\"][wa]", re.IGNORECASE)
WRITERS = ("Write", "Edit", "MultiEdit")
SHELLS = ("Bash", "PowerShell")
# A transcript this big is not parsed: hooks have seconds. Measured 2026-10-07: 0.31 s for the
# largest real one (53 MB), so 200 MB stays near 1.2 s.
MAX_TRANSCRIPT = 200_000_000
# A window whose session wrote nothing for this long holds no claim: a PID Windows gave to an
# unrelated process would otherwise mark a bucket busy for as long as that process runs.
STALE_S = 24 * 3600


def linked(path):
    """A symlink, or on Windows a junction (os.path.islink misses those)."""
    try:
        return os.path.islink(path) or bool(getattr(os.path, "isjunction", lambda p: False)(path))
    except (OSError, TypeError, ValueError):
        return True


def scratch_ok(root):
    """root/.claude/scratch is a real folder, and neither it nor .claude is a link."""
    if not root:
        return False
    dot = os.path.join(root, ".claude")
    scratch = os.path.join(dot, "scratch")
    return not linked(dot) and not linked(scratch) and os.path.isdir(scratch)


def scratch_root(data):
    """The project root whose .claude/scratch holds the buckets: CLAUDE_PROJECT_DIR, else the
    payload cwd, the first that has one (as kit-session-start.py picks it), is no link and is
    not switched off; None when neither qualifies. Nothing here creates .claude/scratch."""
    roots = [r for r in (os.environ.get("CLAUDE_PROJECT_DIR"), data.get("cwd")) if r]
    return next((r for r in roots if scratch_ok(r) and not kit_off(r)), None)


def safe_dir(bucket, name):
    """bucket/name when it is absent or a real folder right inside the bucket; None when it is a
    link or junction, or resolves elsewhere - a write or prune would follow it out (refuter 6)."""
    path = os.path.join(bucket, name)
    if not os.path.lexists(path):
        return path
    if linked(path) or not os.path.isdir(path):
        return None
    try:
        inside = os.path.normcase(os.path.realpath(path)) == os.path.normcase(
            os.path.join(os.path.realpath(bucket), name))
    except (OSError, ValueError):
        return None
    return path if inside else None


def bucket_dir(root, slug):
    """root/.claude/scratch/<slug> when it is a real bucket folder right under a safe scratch;
    None for a `_` kit folder, a link, or anything outside."""
    if not slug or slug.startswith("_") or not scratch_ok(root):
        return None
    scratch = os.path.realpath(os.path.join(root, ".claude", "scratch"))
    bucket = os.path.join(root, ".claude", "scratch", slug)
    try:
        if linked(bucket) or not os.path.isdir(bucket) or os.path.normcase(
                os.path.dirname(os.path.realpath(bucket))) != os.path.normcase(scratch):
            return None
    except (OSError, ValueError):
        return None
    return bucket


def session_bucket(transcript, root, reads=False):
    """The bucket of the STATE.md this session WROTE last - a Write/Edit target, or a shell
    command that writes it; with reads=True, a session that wrote none but read one (a
    /continue) gets the one it read last. Read from the session's own transcript, so a parallel
    session's STATE.md never counts (review 2026-10-07, refuter 1-3). None when there is none,
    the transcript is unreadable or too big, or the bucket is a symlink, a `_` kit folder or
    outside .claude/scratch."""
    wrote = read = None
    try:
        if os.path.getsize(transcript) > MAX_TRANSCRIPT:
            return None
        f = open(transcript, encoding="utf-8", errors="replace")
    except (OSError, TypeError, ValueError):
        return None
    with f:
        for line in f:
            if "STATE.md" not in line or '"tool_use"' not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if not isinstance(o, dict) or o.get("isSidechain") or o.get("type") != "assistant":
                continue
            for b in (o.get("message") or {}).get("content") or []:
                if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                    continue
                inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                name = b.get("name")
                if name in WRITERS or name == "Read":
                    target, write = str(inp.get("file_path") or ""), name != "Read"
                elif name in SHELLS:
                    target = str(inp.get("command") or "")
                    write = bool(SHELL_WRITE.search(target))
                else:
                    continue
                for m in STATE_PATH.finditer(target):
                    if write:
                        wrote = m.group(1)
                    else:
                        read = m.group(1)
    slug = wrote or (read if reads else None)
    return bucket_dir(root, slug)


def window():
    """This Claude Code window: env CLAUDE_PID, digits only; "" when it is absent."""
    pid = os.environ.get("CLAUDE_PID", "").strip()
    return pid if pid.isdigit() else ""


def _window_file(pid):
    return os.path.join(tempfile.gettempdir(), f"kit-window-{pid}.json")


def alive(pid):
    """Whether process `pid` runs. Never signal 0 on Windows: there os.kill TERMINATES it."""
    pid = int(pid)
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except PermissionError:
            return True
        except OSError:
            return False
        return True
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    k.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    k.CloseHandle.argtypes = (wintypes.HANDLE,)
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    try:
        code = wintypes.DWORD()
        return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        k.CloseHandle(h)


def read_window(pid):
    """The record a window's last SessionStart left: {sid, transcript, root, bucket}; {} if none."""
    try:
        with open(_window_file(pid), encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        return {}
    return rec if isinstance(rec, dict) else {}


def write_window(pid, rec):
    path = _window_file(pid)
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(rec, f)
    os.replace(path + ".tmp", path)


def same_dir(a, b):
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except (OSError, TypeError, ValueError):
        return False


def window_bucket(rec, root):
    """The slug a window's current session works on: what its transcript shows first, else the
    bucket its SessionStart gave it (a /clear lineage the session has not touched yet)."""
    if not same_dir(rec.get("root") or "", root):
        return None
    b = session_bucket(rec.get("transcript") or "", root, reads=True)
    slug = os.path.basename(b) if b else rec.get("bucket")
    return slug if isinstance(slug, str) and slug else None


def busy_buckets(root, me):
    """{slug: pid} of the buckets another LIVE window of this project works on. The record of a
    dead or long-idle window is removed: it holds no claim."""
    out = {}
    for path in glob.glob(os.path.join(tempfile.gettempdir(), "kit-window-*.json")):
        pid = os.path.basename(path)[len("kit-window-"):-len(".json")]
        if not pid.isdigit() or pid == me:
            continue
        rec = read_window(pid)
        transcript = str(rec.get("transcript") or "")
        try:
            # A session just /clear-ed has no transcript file until its first message.
            idle = time.time() - os.path.getmtime(transcript if os.path.isfile(transcript) else path)
            gone = idle > STALE_S or not alive(pid)
        except (OSError, ValueError, OverflowError):
            gone = True
        if gone:
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        slug = window_bucket(rec, root)
        if slug:
            out.setdefault(slug, pid)
    return out
