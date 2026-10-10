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
import json
import os
import re
import sys
import time

from kit_off import HEADER, RULES, kit_off

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


# A touch of a bucket's notes - .claude/scratch/<slug>/STATE.md, FINDINGS.md or DECISIONS.md - in
# a Read/Write/Edit target or a shell command; never a longer name (STATE.md.bak).
NOTE_PATH = re.compile(r"(?:^|[/\\\s\"'=])\.claude[/\\]scratch[/\\]([^/\\\s\"'*?<>|]+)[/\\]"
                       r"(STATE|FINDINGS|DECISIONS)\.md(?![\w-]|\.\w)", re.IGNORECASE)
# Which notes a SHELL command writes is judged per path (bucket handoff-timeline, 2026-10-10): a
# note is written only when IT is the target - of a redirect, of tee / Tee-Object / Set-Content /
# Add-Content / Out-File, of sed or perl -i, as the last word of cp / mv / Copy-Item / Move-Item,
# or of a write-mode open() / Path().write_text() / [IO.File]::Write*. The test it replaces (any
# `>` anywhere in the command) made `x 2>/dev/null; head .claude/scratch/a/STATE.md` a write of
# a's STATE.md: a session that only READ a closed task's notes was filed under that task, and
# session_bucket() could hand this window's /clear to it.
REDIRECT_END = re.compile(r"(?:(?<![-=<>&])>>?|&>>?)\|?$")
STAGE_WRITER = re.compile(r"(?:sudo\s+)?(?:tee|Tee-Object|Set-Content|Add-Content|Out-File|touch|New-Item)\b",
                          re.IGNORECASE)
IN_PLACE = re.compile(r"(?:sudo\s+)?(?:sed|perl)\b.*?(?:\s-[A-Za-z]*i[\w.]*|\s--in-place\S*)(?=\s|$)",
                      re.IGNORECASE | re.DOTALL)
COPIER = re.compile(r"(?:sudo\s+)?(?:cp|mv|copy|move|Copy-Item|Move-Item|cpi|mi)\b", re.IGNORECASE)
# A file mode that writes: 'w', 'a', 'x', or '+' with any of r/b/t ('ascii' is no mode).
_MODE = r"[rbuf]{0,2}['\"](?=[rbtU]*[wax+])[rwxabtU+]{1,4}['\"]"
CODE_WRITE = re.compile(
    r"\bopen\(\s*[rbuf]{0,2}(['\"])([^'\"\n]*)\1\s*,\s*(?:[^)\n]*?\bmode\s*=\s*)?" + _MODE
    + r"|\bPath\(\s*[rbuf]{0,2}(['\"])([^'\"\n]*)\3\s*\)\s*\.(?:write_text|write_bytes|open\(\s*" + _MODE + r")"
    r"|::(?:Write|Append)All(?:Text|Lines|Bytes)\(\s*(['\"])([^'\"\n]*)\5", re.IGNORECASE)
# The same writes through a name: `p = pathlib.Path(r'.claude/scratch/a/STATE.md')` ... `open(p, 'w')`.
CODE_VAR = re.compile(r"\b([A-Za-z_]\w*)\s*=\s*(?:[\w.]*Path\(\s*)?[rbuf]{0,2}(['\"])([^'\"\n]*)\2", re.IGNORECASE)
# A write through any name. In a code heredoc that has one, a note path handed over as a list
# item or a call argument (`for p, old, new in [('.../STATE.md', ...)]: open(p, 'w')`) is written.
NAME_WRITE = re.compile(r"\bopen\(\s*[A-Za-z_][\w.]*\s*,\s*(?:[^)\n]*?\bmode\s*=\s*)?" + _MODE
                        + r"|\b[A-Za-z_]\w*\.(?:write_text|write_bytes)\(|\b[A-Za-z_]\w*\.open\(\s*(?:mode\s*=\s*)?"
                        + _MODE, re.IGNORECASE)
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_]\w*)\1")
# A heredoc body is one of three things. DATA - fed to cat/tee/git (a file's or a message's
# text): a note named in it is no touch. SHELL - fed to bash/sh/pwsh: judged as shell. CODE -
# anything else (python, node...), or a script file being written to run next (`cat > fix.py`):
# only its write calls count (CODE_WRITE, CODE_VAR).
DATA_SINK = re.compile(r"^\s*(?:sudo\s+)?(?:cat|tee|git)\b")
SHELL_RUNNER = re.compile(r"(?:^|[\s|])(?:sudo\s+)?(?:bash|sh|zsh|dash|ksh|pwsh|powershell)(?:\.exe)?(?=\s|$)",
                          re.IGNORECASE)
SCRIPT_FILE = re.compile(r"\.(?:py|sh|bash|zsh|ps1|psm1|js|mjs|cjs|ts|rb|pl|php)\b", re.IGNORECASE)
SHELL_SCRIPT = re.compile(r"\.(?:sh|bash|zsh|ps1|psm1)\b", re.IGNORECASE)
# A path handed straight to a call that only reads or inspects it is no write, whatever else
# the code writes through a name.
READ_CALL = re.compile(r"\b(?:open|Path|exists|isfile|isdir|getsize|getmtime|stat|glob|listdir)\(\s*[rbuf]{0,2}['\"]$",
                       re.IGNORECASE)
# `cd <...>/.claude/scratch/<slug> && cat >> FINDINGS.md`: a bare note name after a cd into a
# bucket is that bucket's note (293 such commands in 544 transcripts; neither test saw them).
CD_INTO = re.compile(r"(?:^|[;&|(\n])\s*(?:cd|pushd|Push-Location|Set-Location)(?:\s+-(?:Literal)?Path)?\s+[\"']?"
                     r"[^\s\"';&|]*?\.claude[/\\]scratch[/\\]([^/\\\s\"'*?<>|;&]+)[/\\]?[\"']?(?=\s|[;&|)]|$)",
                     re.IGNORECASE)
CD_ANY = re.compile(r"(?:^|[;&|(\n])\s*(?:cd|pushd|popd|Push-Location|Pop-Location|Set-Location)\b", re.IGNORECASE)
# Into the scratch folder itself, then to a bucket by its bare name - `cd .claude/scratch && ...` then
# `cd <slug> && cat > STATE.md`, or `<slug>/STATE.md` from there. Measured 2026-10-11 (bucket
# kit-records-integration): a session that wrote its STATE.md that way was filed under no task, so it
# left no digest and the next /continue resumed without its conversation.
CD_SCRATCH = re.compile(r"(?:^|[;&|(\n])\s*(?:cd|pushd|Push-Location|Set-Location)(?:\s+-(?:Literal)?Path)?\s+[\"']?"
                        r"[^\s\"';&|]*?\.claude[/\\]scratch[/\\]?[\"']?(?=\s|[;&|)]|$)", re.IGNORECASE)
CD_SLUG = re.compile(r"(?:^|[;&|(\n])\s*(?:cd|pushd|Push-Location|Set-Location)(?:\s+-(?:Literal)?Path)?\s+[\"']?"
                     r"([A-Za-z0-9][A-Za-z0-9._-]*)[/\\]?[\"']?(?=\s|[;&|)]|$)", re.IGNORECASE)
SLUG_NOTE = re.compile(r"(?<![\w/\\.-])(?:\.[/\\])?([A-Za-z0-9][A-Za-z0-9._-]*)[/\\](STATE|FINDINGS|DECISIONS)\.md"
                       r"(?![\w-]|\.\w)", re.IGNORECASE)
BARE_NOTE = re.compile(r"(?<![\w/\\.-])(?:\.[/\\])?(STATE|FINDINGS|DECISIONS)\.md(?![\w-]|\.\w)", re.IGNORECASE)
# A shell name holding a note or a bucket: `F=.claude/scratch/a/FINDINGS.md; printf x >> "$F"`,
# `B=.claude/scratch/a; cat >> "$B/FINDINGS.md"`, PowerShell `$f = '...'`.
SHELL_VAR = re.compile(r"(?:^|[;&|(\n\s])(?:export\s+|local\s+|\$)?([A-Za-z_]\w*)\s*=\s*([\"']?)([^\s\"';&|]*?"
                       r"\.claude[/\\]scratch[/\\]([^/\\\s\"'*?<>|;&]+)(?:[/\\](STATE|FINDINGS|DECISIONS)\.md)?)"
                       r"[/\\]?\2(?=\s|[;&|)]|$)", re.IGNORECASE)
WORD_STOP = " \t\n\"'<>|;&()=`"
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


# project-records (bucket kit-records-integration, D001): a project whose permanent record is its
# docs/ folder, kept by the user's project-records skill (copied in by the typed /records-install).
# There a decision, finding, lesson, question or work item has ONE home, its docs/ entry with its
# id (D-/F-/L-/Q-/B-NNN), and a bucket is working notes that cite the id. Measured 2026-10-11: with
# both on, a bucket restated docs entries and numbered its own decisions D001 beside docs' D-005.
# The sign is the one records-hook.mjs keys on, docs/TIMELINE.md, plus the skill itself; none of
# it may be a link (a cloned repo could commit one pointing anywhere).
RECORDS_SIGNS = (os.path.join("docs", "TIMELINE.md"), os.path.join(".claude", "skills", "project-records", "SKILL.md"))
RECORD_ID_RE = re.compile(r"(?<![\w-])D-\d{3}(?!\d)")
RECORD_HEAD_RE = re.compile(r"^###[ \t]+(D-\d{3})\b[^\n]*", re.MULTILINE)
ROADMAP_OPEN_RE = re.compile(r"^\s*- \[ \] (.+)$", re.MULTILINE)  # records-hook.mjs's own pattern
RECORD_HEAD_CHARS = 240
RECORDS_READ_MAX = 2_000_000  # a docs file past this is not read: hooks have seconds


def records_project(root):
    """True when root keeps the project-records record: docs/TIMELINE.md and the skill, no link on the way."""
    if not root:
        return False
    if any(linked(os.path.join(root, d)) for d in ("docs", ".claude")):
        return False
    return all(os.path.isfile(os.path.join(root, p)) and not linked(os.path.join(root, p)) for p in RECORDS_SIGNS)


def _record_text(root, name):
    path = os.path.join(root, "docs", name)
    try:
        if linked(path) or os.path.getsize(path) > RECORDS_READ_MAX:
            return ""
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def record_heads(root, texts):
    """The docs/DECISIONS.md heading of every decision id the texts cite, in the order first cited:
    the entry's title, date and status as the record writes them (`### D-005 — ... · DECIDED`, a
    replaced one says so). An id with no heading there is left out."""
    ids = list(dict.fromkeys(i for t in texts for i in RECORD_ID_RE.findall(t or "")))
    if not ids:
        return []
    heads = {}
    for m in RECORD_HEAD_RE.finditer(_record_text(root, "DECISIONS.md")):
        heads.setdefault(m.group(1), m.group(0).strip()[:RECORD_HEAD_CHARS])
    return [heads[i] for i in ids if i in heads]


def roadmap_next(root):
    """The first open line of docs/ROADMAP.md (what records-hook.mjs names at session start), or ""."""
    m = ROADMAP_OPEN_RE.search(_record_text(root, "ROADMAP.md"))
    return m.group(1).strip()[:RECORD_HEAD_CHARS] if m else ""


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


def _heredoc_bodies(cmd):
    """[(kind, start, end)] of every terminated heredoc body, end exclusive (its terminator line
    included); kind is data, shell or code (see DATA_SINK)."""
    out, lines, pos = [], cmd.split("\n"), []
    at = 0
    for line in lines:
        pos.append(at)
        at += len(line) + 1
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        m = HEREDOC.search(line)
        if not m:
            continue
        name, tabs = m.group(2), "\t" if line[m.start():m.start() + 3] == "<<-" else ""
        end = next((j for j in range(i, len(lines)) if lines[j].rstrip("\r").lstrip(tabs) == name), None)
        if end is None:
            continue  # never terminated: the rest stays shell text, as bash may read it
        stage = re.split(r"&&|\|\||[;|(]", line[:m.start()])[-1]
        piped = line[m.end():].split("|", 1)[1] if "|" in line[m.end():] else ""
        if SHELL_RUNNER.search(piped or stage) or (not piped and SHELL_SCRIPT.search(stage)):
            kind = "shell"
        elif not piped and DATA_SINK.match(stage) and not SCRIPT_FILE.search(stage):
            kind = "data"
        else:
            kind = "code"
        out.append((kind, pos[i], min(len(cmd), pos[end] + len(lines[end]))))
        i = end + 1
    return out


def _blank(text, ranges):
    """`text` with each [start, end) range turned to spaces, newlines kept: same length."""
    chars = list(text)
    for a, b in ranges:
        for k in range(a, b):
            if chars[k] != "\n":
                chars[k] = " "
    return "".join(chars)


def _quote_spans(s):
    """[(start, end)] of every quoted string, end exclusive: '...' (no escapes, $'...' takes \\),
    "..." (\\ escapes), a PowerShell here-string @'...'@ / @"..."@ whole; a backslash outside
    quotes escapes the next character (`'it'\\''s'` is one word). An open quote runs to the end."""
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "@" and s[i + 1:i + 2] in ("'", '"') and s[i + 2:i + 3] in ("\n", "\r"):
            close = s.find("\n" + s[i + 1] + "@", i + 2)
            j = n if close < 0 else close + 3
        elif c in "'\"":
            esc = c == '"' or (i > 0 and s[i - 1] == "$")
            j = i + 1
            while j < n and s[j] != c:
                j += 2 if esc and s[j] == "\\" else 1
            j = min(j + 1, n)
        else:
            i += 1
            continue
        out.append((i, j))
        i = j
    return out


def _written(shell, masked, spans, c0, end):
    """Whether the note whose path starts at c0 (`.claude`, or a bare name) and ends at `end`
    is a write target in the shell text."""
    q = next(((a, b) for a, b in spans if a < c0 < b), None)
    if q:
        start, end = q  # a quoted path is one shell word, quotes included
    else:
        start = c0
        while start > 0 and shell[start - 1] not in WORD_STOP:
            start -= 1
    before, after = masked[:start].rstrip(), masked[end:]
    if before.endswith("<"):
        return False  # `< note`: an input redirect
    if REDIRECT_END.search(before):
        return True
    stage = re.split(r"&&|\|\||[;|\n(`]", before)[-1].lstrip()
    if STAGE_WRITER.match(stage) or IN_PLACE.match(stage):
        return True
    return bool(COPIER.match(stage)) and re.match(r"[ \t]*(?:$|[;&|)\n`])", after) is not None


# Whose bucket a note path names is judged by what stands before `.claude/scratch/` (2026-10-10):
# a copy elsewhere - a sandbox `$T/.claude/scratch/a/STATE.md` with T=$(mktemp -d), another
# project's absolute path - is not this project's task. Over 805 real transcripts that filed 1
# session in a closed task; every real write (~1,530) was relative, under the root, behind
# $CLAUDE_PROJECT_DIR, or behind a name the same command set to the root.
PREFIX_STOP = " \t\n\"'<>|;&=`"
PREFIX_VAR = re.compile(r"(?:\$\{?(?:env:)?(\w+)\}?|\$\((\w+)\)|%(\w+)%)(.*)$", re.IGNORECASE)


def path_prefix(text, at):
    """The word part before position `at` (where `.claude` starts) in a shell command."""
    i = at
    while i > 0 and text[i - 1] not in PREFIX_STOP:
        i -= 1
    return text[i:at]


def note_here(prefix, root, cmd=""):
    """Whether a note path whose text before `.claude` is `prefix` lies in `root`'s scratch: a
    relative path does (the session works in its root), an absolute one only when it is the
    root, `$CLAUDE_PROJECT_DIR` / `$PWD` / `$(pwd)` do, and another name only when `cmd` itself
    sets it to such a path. No root to judge by: yes, as before."""
    head = prefix.rstrip("/\\")
    if root is None or not re.match(r"[A-Za-z]:|[/\\$%~]", prefix):
        return True
    if head[:1] in "$%":
        m = PREFIX_VAR.match(head)
        if not m:
            return False
        name, rest = next(g for g in m.groups()[:3] if g), m.group(4)
        if name.upper() in ("CLAUDE_PROJECT_DIR", "PWD"):
            return True
        a = re.search(r"(?:^|[;&|\n\s(])\$?" + re.escape(name) + r"\s*=\s*([\"']?)([^\"'\s;&|$()]+)\1(?=[\s;&|)]|$)", cmd)
        if not a:
            return False  # T=$(mktemp -d), or a name this command never set
        head = a.group(2) + rest
        if not re.match(r"[A-Za-z]:|[/\\~]", head):
            return True
    head = os.path.expanduser(head)
    if os.name == "nt":
        head = re.sub(r"^[/\\]([A-Za-z])(?=[/\\]|$)", r"\1:", head)  # Git Bash /d/x = d:/x
    return same_dir(head or os.sep, root)


def shell_notes(cmd, root=None):
    """[(slug, NOTE, written)] for each bucket note a shell command names, in order; NOTE is
    STATE, FINDINGS or DECISIONS. `written` only when that very path is the write target (see
    REDIRECT_END and the patterns below it). A note named in a data heredoc's body is text being
    written somewhere else and counts for nothing; in a code body only a write call counts."""
    cmd = str(cmd or "")
    if "scratch" not in cmd.lower():
        return []
    bodies = _heredoc_bodies(cmd)
    work = _blank(cmd, [(a, b) for k, a, b in bodies if k == "data"])    # what code may say
    shell = _blank(cmd, [(a, b) for k, a, b in bodies if k != "shell"])  # what the shell parses
    in_code = [(a, b) for k, a, b in bodies if k == "code"]
    spans = _quote_spans(shell)
    masked = list(shell)
    for a, b in spans:  # a quoted string is no shell syntax: `grep "> x"` holds no redirect
        masked[a + 1:b - 1] = "_" * max(0, b - a - 2)
    masked = "".join(masked)
    code = set()  # where `.claude` starts in a path that code opens for writing
    for m in CODE_WRITE.finditer(work):
        g = next(k for k in (2, 4, 6) if m.group(k) is not None)
        for n in NOTE_PATH.finditer(m.group(g)):
            code.add(m.start(g) + n.start() + n.group(0).lower().index(".claude"))
    named = set()  # note paths bound to a name: judged by that name's writes alone
    for m in CODE_VAR.finditer(work):
        notes = [m.start(3) + n.start() + n.group(0).lower().index(".claude") for n in NOTE_PATH.finditer(m.group(3))]
        named.update(notes)
        var = re.escape(m.group(1))
        if notes and re.search(r"\bopen\(\s*" + var + r"\s*,\s*(?:[^)\n]*?\bmode\s*=\s*)?" + _MODE
                               + r"|\b" + var + r"\.write_(?:text|bytes)\(|\b" + var + r"\.open\(\s*(?:mode\s*=\s*)?"
                               + _MODE + r"|\bPath\(\s*" + var + r"\s*\)\s*\.write_(?:text|bytes)\(",
                               work[m.end():], re.IGNORECASE):
            code.update(notes)
    for a, b in ((a, b) for k, a, b in bodies if k == "code"):
        if NAME_WRITE.search(work, a, b):
            for n in NOTE_PATH.finditer(work, a, b):
                c = n.start() + n.group(0).lower().index(".claude")
                q = max(work.rfind("'", a, c), work.rfind('"', a, c))  # the literal's opening quote
                if c not in named and not (q >= 0 and READ_CALL.search(work, a, q + 1)):
                    code.add(c)
    found = []  # (where the note is named, where its `.claude` starts, slug, NOTE, written)
    for m in NOTE_PATH.finditer(work):
        c0 = m.start() + m.group(0).lower().index(".claude")
        coded = any(a <= c0 < b for a, b in in_code)
        found.append((c0, c0, m.group(1), m.group(2).upper(),
                      c0 in code or (not coded and _written(shell, masked, spans, c0, m.end()))))
    stops = [m.start() for m in CD_ANY.finditer(shell)]
    for cd in CD_INTO.finditer(shell):
        until = next((s for s in stops if s > cd.start()), len(shell))
        at = cd.start() + cd.group(0).lower().index(".claude")
        for m in BARE_NOTE.finditer(shell, cd.end(), until):
            found.append((m.start(), at, cd.group(1), m.group(1).upper(), _written(shell, masked, spans, m.start(), m.end())))
    for cd in CD_SCRATCH.finditer(shell):
        at = cd.start() + cd.group(0).lower().index(".claude")
        nxt = next((s for s in stops if s > cd.start()), len(shell))
        for m in SLUG_NOTE.finditer(shell, cd.end(), nxt):  # `<slug>/STATE.md` from the scratch folder
            found.append((m.start(), at, m.group(1), m.group(2).upper(), _written(shell, masked, spans, m.start(), m.end())))
        sub = CD_SLUG.match(shell, nxt) if nxt < len(shell) else None  # the very next cd: into a bucket
        if sub:
            until = next((s for s in stops if s > nxt), len(shell))
            for m in BARE_NOTE.finditer(shell, sub.end(), until):
                found.append((m.start(), at, sub.group(1), m.group(1).upper(),
                              _written(shell, masked, spans, m.start(), m.end())))
    for v in SHELL_VAR.finditer(shell):
        if any(a < v.start(1) < b for a, b in spans):
            continue  # `echo "F=..."`: an assignment inside a quoted string is text
        name, slug, note = re.escape(v.group(1)), v.group(4), (v.group(5) or "").upper()
        at = v.start(3) + v.group(3).lower().index(".claude")
        use = re.compile(r"\$\{?" + name + r"\}?" + (r"(?![\w/\\])" if note else
                                                     r"[/\\](STATE|FINDINGS|DECISIONS)\.md(?![\w-]|\.\w)"), re.IGNORECASE)
        for m in use.finditer(shell, v.end()):
            found.append((m.start(), at, slug, note or m.group(1).upper(), _written(shell, masked, spans, m.start(), m.end())))
    return [(slug, note, w) for _, at, slug, note, w in sorted(found)
            if note_here(path_prefix(cmd, at), root, cmd)]


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
                    path = str(inp.get("file_path") or "")
                    notes = [(m.group(1), m.group(2).upper(), name != "Read") for m in NOTE_PATH.finditer(path)
                             if note_here(path[:m.start() + m.group(0).lower().index(".claude")], root)]
                elif name in SHELLS:
                    notes = shell_notes(inp.get("command"), root)
                else:
                    continue
                for slug, note, written in notes:
                    if note != "STATE":
                        continue
                    if written:
                        wrote = slug
                    else:
                        read = slug
    slug = wrote or (read if reads else None)
    return bucket_dir(root, slug)


def window():
    """This Claude Code window: env CLAUDE_PID, digits only; "" when it is absent."""
    pid = os.environ.get("CLAUDE_PID", "").strip()
    return pid if pid.isdigit() else ""


def tmpdir():
    """tempfile.gettempdir() without importing tempfile - ~7 ms of every hook event (2026-10-10):
    the first of TMPDIR, TEMP, TMP that is a folder, gettempdir()'s own order; tempfile itself
    only when none is. A tempdir set in-process (the self-tests set one) wins, as it does there."""
    t = sys.modules.get("tempfile")
    if t is not None and getattr(t, "tempdir", None):
        return t.tempdir
    for k in ("TMPDIR", "TEMP", "TMP"):
        d = os.environ.get(k)
        if d and os.path.isdir(d):
            return os.path.abspath(d)
    import tempfile
    return tempfile.gettempdir()


def _window_file(pid):
    return os.path.join(tmpdir(), f"kit-window-{pid}.json")


# kit-context's per-session band marker. A session that ends above the threshold (the usual
# handoff + /clear) leaves it behind; measured 2026-10-10: 41 had piled up. Stale after 30 days:
# Claude Code deletes a transcript after cleanupPeriodDays (default 30), so no older session can
# be resumed and re-blocked for a band it already handled.
CONTEXT_MARKER = "kit-context-"
CONTEXT_MARKER_AGE = 30 * 86400
# The Stop hook reads the transcript every turn. Read whole, that is O(transcript) a turn - 26-200 ms
# measured on real 3-53 MB transcripts (bucket kit-default-off-optimize) - so its readers keep their
# state beside the context marker (read_state: swept after a day, deleted at SessionEnd) and read only
# the lines appended since the last turn; ".digest" times the last digest rebuild (kit-context, D005).
READ_STATES = (".scan", ".usage", ".digest")
READ_STATE_AGE = 86400
STATE_VERSION = 1  # bump when a reader's kept fields change: a kept state of another version is a miss


def context_marker(sid):
    return os.path.join(tmpdir(), CONTEXT_MARKER + re.sub(r"[^A-Za-z0-9._-]", "_", sid or "unknown"))


def read_state(sid, kind):
    """The file one Stop-hook reader keeps this session's state in; `kind` one of READ_STATES."""
    return context_marker(sid) + kind


def drop_read_states(sid):
    for kind in READ_STATES:
        try:
            os.remove(read_state(sid, kind))
        except OSError:
            pass


def resumed(cache, f, ident, fresh):
    """The state an earlier read of this same transcript kept in `cache`, with `f` (opened "rb")
    at its offset - when its version and every `ident` value match, every `fresh` field has the
    type it has there, and the transcript only grew since (the byte before the offset still ends a
    line); else `fresh` from offset 0, with `f` at 0. No `cache`: always fresh."""
    ident = {"v": STATE_VERSION, **ident}
    try:
        with open(cache, encoding="utf-8") as c:
            st = json.load(c)
        off = st["offset"]
        if (not isinstance(off, int) or off < 0 or any(st.get(k) != v for k, v in ident.items())
                or any(not isinstance(st.get(k), type(v)) for k, v in fresh.items())):
            raise ValueError(cache)
        if off:
            f.seek(off - 1)
            if f.read(1) != b"\n":
                raise ValueError(cache)
        f.seek(off)
        return st
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        f.seek(0)
        return {**ident, "offset": 0, **fresh}


def keep(cache, state):
    """`state` into `cache`, owner-only: it holds the conversation's text."""
    write_atomic(cache, json.dumps(state, ensure_ascii=False), private=True)


def write_atomic(path, data, private=False):
    """Whole file or the old one, never half: a tmp name of this process's own, created new - so a
    link a cloned repo planted beside the target is never written through (review 2026-10-10) - then
    a rename, which replaces a link at `path` itself and never follows it; a rename that a reader's
    open handle blocks on Windows is retried once. `data`: str (UTF-8, LF kept) or bytes; `private`:
    owner-only. Two hooks writing one file at once each use their own tmp."""
    tmp = f"{path}.{os.getpid()}.{time.monotonic_ns() % 10 ** 9}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600 if private else 0o666)
    with os.fdopen(fd, "wb") as f:
        f.write(data.encode("utf-8") if isinstance(data, str) else data)
    for attempt in (0, 1):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            time.sleep(0.05)


def installed_rules():
    """The kit's rules where install.ps1 puts them: ~/.claude/kit/, beside this hooks folder."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "kit", "orchestration-kit.md")


def rules_blocker(root):
    """Why the kit's rules copy may not be written in `root`, or None. `root`'s .claude is Claude
    Code's own config folder (the home folder: a copy there would be the GLOBAL rules file and turn
    the kit on in every project); a link on the way (a cloned repo can commit one - the write
    would land where it points); a file of that name that is the project's own (no HEADER)."""
    claude = os.path.join(root, ".claude")
    config = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.path.expanduser("~"), ".claude")
    if os.path.normcase(os.path.realpath(claude)) == os.path.normcase(os.path.realpath(config)):
        return "this folder's .claude is Claude Code's own config (the home folder): a copy there would load in every project"
    copy = os.path.join(root, RULES)
    if any(linked(p) for p in (claude, os.path.dirname(copy), copy)):
        return "a link on the way there"
    try:
        with open(copy, "rb") as f:
            if f.read(len(HEADER)) != HEADER:
                return "the project's own file of that name (no `<!-- orchestration-kit` header)"
    except FileNotFoundError:
        pass
    except OSError as e:
        return str(e)
    return None


def sync_rules(root, rules):
    """The rules copy in `root` made equal to `rules` (bytes, HEADER first): "written" or "same".
    Ask rules_blocker() first."""
    copy = os.path.join(root, RULES)
    try:
        with open(copy, "rb") as f:
            if f.read() == rules:
                return "same"
    except OSError:
        pass
    os.makedirs(os.path.dirname(copy), exist_ok=True)
    write_atomic(copy, rules)
    return "written"


def sweep_context_markers():
    """Delete context markers older than CONTEXT_MARKER_AGE: plain files only, never a link or a
    folder. ~9 ms over 20,741 temp entries (2026-10-10). Returns how many it deleted."""
    now, gone = time.time(), 0
    with os.scandir(tmpdir()) as it:
        for e in it:
            if not e.name.startswith(CONTEXT_MARKER):
                continue
            # A read state is rebuilt by its next read, and holds the conversation's text: a day is
            # enough (a tmp a crash left goes with it). A marker keeps a resumed session's band.
            age = READ_STATE_AGE if e.name.endswith(READ_STATES + (".tmp",)) else CONTEXT_MARKER_AGE
            try:
                if (e.is_file(follow_symlinks=False) and not linked(e.path)
                        and now - e.stat(follow_symlinks=False).st_mtime > age):
                    os.remove(e.path)
                    gone += 1
            except OSError:
                pass
    return gone


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
    write_atomic(_window_file(pid), json.dumps(rec))


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
    import glob  # here: a session start alone needs it, never the per-turn hooks
    out = {}
    for path in glob.glob(os.path.join(tmpdir(), "kit-window-*.json")):
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
