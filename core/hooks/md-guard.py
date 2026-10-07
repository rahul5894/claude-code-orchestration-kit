"""PreToolUse guard: big markdown docs are read in windows, and never left half-read.

Read  -> a .md of <=300 lines, or a doc an agent must have whole (CLAUDE.md, AGENTS.md,
         SKILL.md, anything under .claude/scratch, briefs/, reports/, handoffs/, memory/),
         passes untouched. Any other .md over 300 lines read with no limit (or one over 300)
         is REWRITTEN, not denied: the call goes on with limit 300 and the model is handed the
         doc's heading outline with line numbers and the offsets still unread. Measured
         2026-10-07: after a deny the agent read the doc whole 0 of 14 times (FINDINGS F4).
Bash  -> deny when cat/sed/awk/grep/rg/head/tail READ a .md path that resolves to a file over
         300 lines, with no column cap. Writes (heredoc, redirect, sed -i, tee), counts and
         capped output pass. A path that resolves to nothing (a search string, a file the same
         command creates, an unknown variable) passes: 64% of the shell denials since 09-29
         were such paths or small files (F5). `$VAR`, `${VAR}` and `for v in ...` loop
         variables are expanded first, from the command's own assignments and the env.
Bash/PowerShell -> deny outright when the payload's agent_type is a read-only
         agent and the command has a named write shape (redirect, sed -i, tee,
         rm/mv/cp, tree-changing git, a write-mode open(), a package install).
Exit 0 + JSON on stdout = decision. Any crash = allow (fail open, dev tool).
Self-check: python md-guard_test.py
"""
import glob
import json
import os
import re
import sys

# The hook's own folder, explicitly: under PYTHONSAFEPATH=1 (or python -P / -I) the script dir
# is not on sys.path, the import fails and the hook exits 1 - which fails open (refuter-02).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_off import kit_off  # noqa: E402

MAX_LINES = 300
CAP_RE = re.compile(
    # `grep -l` is deliberately NOT here, though it prints file names only. Tried and
    # reverted 2026-09-19: `[^|]*` caps the REGEX, not the command, so
    # `grep -rl x --include=*.md . | xargs cat` matched and dumped every file, and the flag
    # pattern also matched inside a search string (`grep -rn "use -all mode" big.md`).
    # Both were allowed by that hunk and both print content. The one-token `| cut -c1-300`
    # in the deny message is the supported way through.
    r"\bqmd\b|cut -c|--max-columns|\s-o\s|\bwc\b|\b(?:grep|rg)\b[^|]*\s-c\b"
    r"|\.Substring\(|Measure-Object"
)
WRITE_RE = re.compile(
    r"<<|>\s*\"?[^|\s]*\.md\b|\bsed\s+-i|\bawk\s+-i|\btee\b", re.IGNORECASE
)
READERS = re.compile(
    r"\b(?:cat|sed|awk|grep|rg|head|tail|less|more"
    r"|Get-Content|gc|type|Select-String|sls)\b", re.IGNORECASE
)
MD_PATH = re.compile(r"[^\s\"'|<>]+\.md\b", re.IGNORECASE)
# A heredoc whose body is data (D009): a file-write line (`cat >[>] f`, `tee [-a] f`) whose
# delimiter is quoted (`<<'EOF'`, `<<"EOF"`, `<<-'EOF'`), so nothing in the body expands.
# Both are matched on the masked line (see _mask), never the `<<<` here-string.
# A WHITELIST: the whole masked line must be one of these shapes, else nothing is stripped.
# The target allows no `;|&<>()$` or quote, so `cat > f;bash <<'EOF'`, `tee >(bash) <<'EOF'`
# and a second `<<` on the line never match - in each something else runs the body.
_PATH = r"[\w./\\:~-]+"
# A write target may also start with a plain `$VAR`/`${VAR}` or be one quoted string (masked to
# `"___"`): the body still goes to cat/tee's stdin, and the head line is judged as it was.
_TARGET = r"(?:\$\{?\w+\}?[\w./\\:~-]*|\"_*\"|'_*'|" + _PATH + r")"
_CD = r"\s*(?:cd\s+" + _PATH + r"\s*&&\s*)?"
HEREDOC_WRITE_RES = (
    re.compile(_CD + r"(?:cat\s*>>?\s*" + _TARGET + r"|tee\s+(?:-a\s+)?" + _TARGET + r")"
               r"\s+<<-?\s*(['\"])(\w+)\1\s*"),
    re.compile(_CD + r"cat\s+<<-?\s*(['\"])(\w+)\1\s*>>?\s*" + _TARGET + r"\s*"),
)

# A read-only agent's verdict is discarded whole if the tree moved under it, so the shell
# writes it can name are denied here rather than found afterwards in a git diff.
# A denylist of named write shapes; the prose prohibition and the git-status diff catch
# the rest
READ_ONLY_AGENTS = {"refuter", "debugger"}
# A discard target: writing there changes nothing.
_DISCARD = r"(?:/dev/null|\$null|nul)(?![\w./\\-])"
# A redirect whose target is a FILE: `>f`, `>>f`, `N>f`, `&>f`, `&>>f`. Not an fd merge
# (`2>&1`, `1>&2`) and not a discard. Judged on the quote-stripped command (DECISIONS 8), so
# `grep -n "->"` and `awk '$1 > 5'` are search strings, not redirects; the `-=<>&` lookbehind
# keeps an UNquoted arrow out too.
REDIRECT_RE = re.compile(
    r"(?:(?<![-=<>&])>>?|&>>?)(?!&)\s*(?!" + _DISCARD + r")\S", re.IGNORECASE)
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
# Every git subcommand that moves the working tree, the index, or a remote. `stash`,
# `worktree` and `branch` have read-only forms, so each is matched by its write form only.
_GIT_WRITE = (r"\bgit\s+(?:add|commit|checkout|switch|reset|clean|restore|rm|mv|push|pull"
              r"|fetch|merge|rebase|apply|am|cherry-pick|revert|init|config|tag|update-ref"
              r"|filter-branch|submodule)\b"
              r"|\bgit\s+stash\b(?!\s+(?:list|show))"
              r"|\bgit\s+worktree\b(?!\s+list)"
              r"|\bgit\s+branch\b[^;&|\n]*\s-[dDmMc]\b")
# The two commands the project CLAUDE.md forbids every agent to run: both write ~/.claude.
# kit_switch.py writes a project's settings.local.json and its kit-off marker. (install\.ps1
# matches uninstall.ps1 too.)
_FORBIDDEN = r"|install\.ps1|verify_live\.py|kit_switch\.py"
# A command word: start of the string or just after a shell separator.
_CMD = r"(?:^|[;&|(\n`]|\$\()\s*"
BASH_WRITE_RE = re.compile(
    r"\bsed\s+-i|\bawk\s+-i|\btee\b|\bperl\s+-\S*i"
    + r"|" + _CMD + r"(?:rm|mv|cp|mkdir|touch|chmod|ln|truncate|install)\b"
    + r"|" + _GIT_WRITE
    + r"|\bfind\b.*\s-delete\b"
    + r"|\bxargs\s+(?:-\S+\s+)*(?:rm|mv|cp|sed\s+-i|tee)\b"
    # `python -c` and heredocs both arrive as one command string, so the write is a Python
    # call or the mode argument of open(), not a shell token.
    + r"|\bopen\(\s*[^)]*,\s*['\"][wax]"
    + r"|open\([^)]*mode\s*=\s*['\"][wax]"
    + r"|\b(?:os\.remove|os\.unlink|os\.rename|os\.makedirs|os\.mkdir|shutil\.\w+"
      r"|\.write_text\(|\.write_bytes\(|\.unlink\(|\.rename\(|\.touch\("
      r"|O_(?:CREAT|WRONLY|RDWR|APPEND|TRUNC)\b)"
    + r"|\bpip\s+install\b|\bnpm\s+(?:install|i|ci)\b|\buv\s+add\b|\bsudo\b"
    + _FORBIDDEN,
    re.IGNORECASE,
)
PS_WRITE_RE = re.compile(
    r"\b(?:Set-Content|Add-Content|Out-File|Clear-Content|Remove-Item|Move-Item"
    r"|Copy-Item|New-Item|Rename-Item)\b"
    + r"|" + _CMD + r"(?:ri|rm|del|mv|cp|sc|ni)\b"
    + r"|" + _GIT_WRITE
    + _FORBIDDEN,
    re.IGNORECASE,
)

# qmd was the suggested route until 2026-09-23 and dropped: in 14 days it was called 10 times
# against ~250 denials here - the model went to grep + Read windows anyway.
# The whole-file line is there because a window is a way to read, not a licence to skim: of 7
# measured Read denials, 3 went on to read part of the file only (2026-09-29) - right for a
# lookup, a silent loss when the task needed the whole document.
HOW = ("Find the spot with `grep -n \"<anchor>\" <file> | cut -c1-300`, then Read that range "
       "with offset+limit. If the task needs the whole file, Read every window in order "
       "(offset 1, 301, 601, ...) to the end; never work from part of it.")


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def _strip_quotes(cmd):
    """The command with every quoted span blanked, so only shell syntax is left to match."""
    return _QUOTED.sub('""', cmd)


def line_count(path):
    try:
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


# Docs an agent must hold whole before it acts: the project's instructions, a skill, and every
# file of the kit's handoff and brief system. Denying or windowing these is how an agent started
# work on half its brief (the user, 2026-10-07: "adhoori information se agent shuru ho gaya. ye
# kabhi nahi hoga"). Read's own token limit still pages a truly huge one, with its notice.
MUST_READ_NAMES = {"claude.md", "agents.md", "claude.local.md", "skill.md"}
MUST_READ_DIRS = re.compile(r"[/\\](?:\.claude[/\\]scratch|briefs|reports|handoffs|memory)[/\\]",
                            re.IGNORECASE)
HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*#*\s*$")
MAX_OUTLINE = 4000  # characters of headings handed over; additionalContext caps at 10,000


def must_read(path):
    return (os.path.basename(path).lower() in MUST_READ_NAMES
            or bool(MUST_READ_DIRS.search(os.path.abspath(path))))


def outline(path):
    """`L<n> <heading>` per markdown heading outside code fences, cut at MAX_OUTLINE chars."""
    out, fence, size = [], False, 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for n, line in enumerate(f, 1):
                if line.lstrip().startswith(("```", "~~~")):
                    fence = not fence
                    continue
                m = None if fence else HEADING.match(line)
                if not m:
                    continue
                row = f"L{n} {m.group(1)} {m.group(2)[:100]}"
                size += len(row) + 1
                if size > MAX_OUTLINE:
                    out.append("... (more headings; grep -n '^#' the file)")
                    break
                out.append(row)
    except OSError:
        return ""
    return "\n".join(out)


def window(inp, path, n):
    """Allow the Read with limit MAX_LINES from its own offset, and hand the model the map:
    which lines it got, which offsets are left, the outline, and when it must read them all.
    No permissionDecision: the rewritten call still goes through the normal permission checks."""
    start = max(int(inp.get("offset") or 1), 1)
    if start > n:
        return  # past the end: Read says so itself, there is no window to give
    end = min(start + MAX_LINES - 1, n)
    rest = [o for o in range(1, n + 1, MAX_LINES) if o > end or o + MAX_LINES - 1 < start]
    ctx = (f"md-guard: {os.path.basename(path)} has {n} lines; this Read returns lines "
           f"{start}-{end} ({(end - start + 1) * 100 // n}%). Unread windows: "
           f"offset {', '.join(map(str, rest[:12]))}{' ...' if len(rest) > 12 else ''} "
           f"(limit {MAX_LINES}). If this document is your task's spec, brief, plan or "
           "instructions, Read every unread window before you act - never work from part of "
           "it. For a lookup, Read the window holding the heading you need.\nOutline:\n"
           + outline(path))
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "updatedInput": dict(inp, offset=start, limit=MAX_LINES),
        "additionalContext": ctx,
    }}))
    sys.exit(0)


def check_read(inp):
    path = inp.get("file_path", "")
    if not path.lower().endswith(".md"):
        return
    n = line_count(path)
    if n <= MAX_LINES or must_read(path):
        return
    limit = inp.get("limit")
    if isinstance(limit, int) and limit <= MAX_LINES:
        return
    window(inp, path, n)


def _resolve(raw, base):
    """The files `raw` names, as a list (a glob can name several), or None if none exist.
    Relative paths resolve against `base`: the payload cwd, moved by any `cd` before them."""
    raw = raw.replace("~", os.path.expanduser("~"))
    if raw.startswith("/") and len(raw) > 3 and raw[2] == "/":  # /d/x -> D:/x
        raw = raw[1].upper() + ":" + raw[2:]
    for cand in (raw, os.path.join(base, raw)):
        if any(c in cand for c in "*?["):
            hits = [h for h in glob.glob(cand) if os.path.isfile(h)]
            if hits:
                return hits
        elif os.path.isfile(cand):
            return [cand]
    return None


def _md_tokens(text):
    """The .md paths named in `text`, quoted or not. Linear: MD_PATH on a long token went
    quadratic (14 s on 100 KB), and a token over 1000 characters is no path anyway."""
    out = []
    for tok in re.split(r"[\s|<>;&(),`]+", text):
        tok = tok.strip("'\"")
        if len(tok) > 1000 or ".md" not in tok.lower():
            continue
        m = re.search(r"[^'\"=]*\.md(?!\w)", tok.rsplit("=", 1)[-1], re.IGNORECASE)
        if m:
            out.append(m.group(0))
    return out


def _scan(cmd, stages=False):
    """Split outside quotes into segments (`&&`, `||`, `;`, newline) or, with stages=True,
    pipeline stages (`|`). None when a quote never closes: then no quote scopes anything."""
    out, cur, q, i = [], [], None, 0
    while i < len(cmd):
        ch = cmd[i]
        if ch == "\\" and q != "'" and i + 1 < len(cmd):
            cur.append(cmd[i:i + 2])
            i += 2
            continue
        if q:
            q = None if ch == q else q
        elif ch in "'\"":
            q = ch
        elif stages and ch == "|":
            out.append("".join(cur))
            cur, i = [], i + 1
            continue
        elif not stages and (cmd[i:i + 2] in ("&&", "||") or ch in ";\n"):
            out.append("".join(cur))
            cur, i = [], i + (2 if cmd[i:i + 2] in ("&&", "||") else 1)
            continue
        cur.append(ch)
        i += 1
    out.append("".join(cur))
    return None if q else out


# A .md filter on a recursive search reads every .md it finds, however it is quoted.
MD_OPTION = re.compile(r"--(?:include|glob)[= ]['\"]?[^\s'\"]*\.md|\s-g\s+['\"]?[^\s'\"]*\.md",
                       re.IGNORECASE)
# The one pipeline shape let through (Bash only; PowerShell pipes path objects INTO readers): a
# first stage that names .md files without printing them, feeding stdin-only filters. Measured
# 2026-09-29: `ls x.md | head` and `git diff --stat -- x.md | tail -1` were ~105 false denials.
LIST_ONLY = re.compile(r"\s*(?:ls|dir|stat|du|find|git\s+(?:status|log(?![^|]*\s(?:-p|--patch)\b)"
                       r"|(?:diff|show)(?=[^|]*\s--(?:stat|name-only|name-status|numstat|shortstat)\b)"
                       r"))\b", re.IGNORECASE)
STDIN_FILTER = re.compile(r"\s*(?:head|tail|wc|sort|uniq|cut|tr|grep)\b"
                          r"(?![^|]*(?:\s-[A-Za-z]*[fr]\b|[<`]|\$\(|\.md\b))", re.IGNORECASE)
CD_RE = re.compile(r"\s*(?:cd|pushd|set-location|sl)\s+(\"[^\"]*\"|'[^']*'|\S+)\s*", re.IGNORECASE)


def _lists_only(seg):
    stages = _scan(seg, stages=True)
    return bool(stages and len(stages) > 1 and LIST_ONLY.match(stages[0])
                and not READERS.search(stages[0]) and not re.search(r"-(?:exec|ok)", stages[0])
                and all(STDIN_FILTER.match(s) for s in stages[1:]))


def _segment_reads_big_md(cmd, base, tool="Bash", env=None):
    """The big .md file this segment reads raw ("*.md" for a recursive .md filter), else ""."""
    # A reader word ANYWHERE in the segment counts: judging only the command position let `<x.md
    # cat`, `find -exec cat`, `eval cat`, `bash -lc` and ~25 more shapes through (refuter,
    # 2026-09-29). Precision comes from the cases below, never from narrowing this.
    paths = _md_tokens(cmd)
    if not paths or not READERS.search(cmd):
        return ""
    if CAP_RE.search(cmd) or WRITE_RE.search(cmd):
        return ""
    if MD_OPTION.search(cmd):
        return "*.md"
    if tool == "Bash" and _lists_only(cmd):
        return ""
    # small files are fine to read raw; only a path that resolves to a big file is gated. An
    # unresolvable one (a search string, a file this command creates, an unset variable) reads
    # nothing big that the guard can know of, and denying it was most of the noise (F5).
    env = env if env is not None else _vars(cmd)
    # A bare name may live in a directory the same segment names (`find <dir> -name x.md -exec
    # cat`), and `git show <rev>:<path>` prefixes the path with the revision (refuter shapes).
    dirs = [d for t in re.split(r"[\s|<>;&()`=]+", cmd) for d in _expand(t.strip("'\""), env)
            if len(d) > 1 and os.path.isdir(d.replace("~", os.path.expanduser("~")))]
    for p in paths:
        for cand in _expand(p, env):
            rev = re.match(r"^[^/\\:\s]{2,}:(.+)$", cand)
            names = [cand] + ([rev.group(1)] if rev else [])
            for name in names:
                found = _resolve(name, base)
                if found is None and not os.path.isabs(name):
                    found = next((r for d in dirs[:10] if (r := _resolve(os.path.join(d, name), base))),
                                 None)
                for f in found or []:
                    if line_count(f) > MAX_LINES:
                        return f
    return ""


_ASSIGN = re.compile(r"(?:^|[\s;&|(])([A-Za-z_]\w*)=(\"[^\"]*\"|'[^']*'|[^\s;&|]*)")
_FOR = re.compile(r"\bfor\s+([A-Za-z_]\w*)\s+in\s+([^;\n]*?)\s*;?\s*do\b")
_VAR = re.compile(r"\$\{?([A-Za-z_]\w*)\}?")


def _vars(cmd):
    """name -> [values]: the command's own `X=...` assignments and `for x in a b c` loop words,
    over the environment's. The full command, not one segment: an assignment before `&&` is
    still set in the segment that reads."""
    env = {k: [v] for k, v in os.environ.items()}
    for name, val in _ASSIGN.findall(cmd):
        env[name] = [val.strip("'\"")]
    for name, words in _FOR.findall(cmd):
        env[name] = [w.strip("'\"") for w in words.split()] or [""]
    return env


def _expand(path, env, depth=0):
    """Every spelling `path` can take once its variables are filled in; a variable with no
    known value stays as it is (and then resolves to nothing)."""
    m = _VAR.search(path)
    if not m or depth > 4:
        return [path]
    vals = env.get(m.group(1))
    if not vals:
        return [path]
    out = []
    for v in vals[:20]:
        out += _expand(path[:m.start()] + v + path[m.end():], env, depth + 1)
    return out[:40]


def _reads_big_md(cmd, base, tool="Bash"):
    """The big .md file `cmd` reads raw, or "" (truthy = deny)."""
    env = _vars(cmd)
    segments = _scan(cmd)
    if segments is None:  # an unclosed quote: split as before quotes were read at all
        segments = re.split(r"&&|\|\||;|\n", cmd)
    for seg in segments:
        cd = CD_RE.fullmatch(seg)
        if cd:
            target = cd.group(1).strip("'\"")
            if target.startswith("/") and len(target) > 2 and target[2] == "/":
                target = target[1].upper() + ":" + target[2:]
            target = os.path.join(base, os.path.expanduser(target))
            if os.path.isdir(target):
                base = target
            continue
        big = _segment_reads_big_md(seg, base, tool, env)
        if big:
            return big
    return ""


def _mask(line):
    """The line with every quoted span's inside turned to `_` (same length, quotes kept) and
    a trailing `# comment` cut, so a `<<` or `cat >` inside a string or a comment is inert."""
    line = _QUOTED.sub(lambda m: m.group()[0] + "_" * (len(m.group()) - 2) + m.group()[0], line)
    return re.sub(r"(?:^|\s)#.*", "", line)


def _strip_heredocs(cmd):
    """The command without the terminated bodies of quoted-delimiter write heredocs (D009):
    only there is a body data. Every other `<<`, and an unterminated body, stays whole, so its
    verdict is what it was before this existed."""
    lines, out, i, clean = cmd.split("\n"), [], 0, True
    while i < len(lines):
        out.append(lines[i])
        masked = _mask(lines[i])
        m = next((m for r in HEREDOC_WRITE_RES if (m := r.fullmatch(masked))), None)
        name = lines[i][m.start(2):m.end(2)] if m and clean else ""
        # The terminator exactly as bash reads it: the bare name, with leading TABs only after
        # `<<-`. A looser match (`  EOF`) ends the body early while bash reads on (refuter-04).
        tabs = "\t" if "<<-" in masked else ""
        end = next((j for j in range(i + 1, len(lines)) if lines[j].lstrip(tabs) == name),
                   None) if re.fullmatch(r"\w+", name) else None
        if end is None:
            # Any other line can leave bash mid-string, mid-heredoc or mid-continuation, so a
            # write line after it is not surely at a command position: `echo "x\"`, `cat <<X`,
            # `bash -s \` would each run a "body" the guard stripped. Stop stripping for good.
            clean = False
        else:
            i = end
        i += 1
    return "\n".join(out)


def check_bash(inp, cwd=None, tool="Bash"):
    # Bodies go for this READ check only. Write detection in main() reads the raw command,
    # or `bash <<EOF` would hide any write inside its body (D007).
    cmd = _strip_heredocs(inp.get("command", ""))
    # judge each `a && b ; c || d` segment on its own (split outside quotes, so a `;` inside a
    # sed script does not cut its `| cut -c` off): `rm x.md && git status | head` must not trip
    # on the `head` of an unrelated segment
    big = _reads_big_md(cmd, cwd if cwd and os.path.isdir(cwd) else os.getcwd(), tool)
    if big:
        # The map goes with the refusal, so the next call can be the right Read window.
        what = ("a recursive .md search" if big == "*.md" else
                f"{os.path.basename(big)} ({line_count(big)} lines)")
        tail = "" if big == "*.md" else (
            " A doc the agent must have whole (CLAUDE.md, a brief, a handoff) Reads whole with "
            "no limit. Outline:\n" + outline(big))
        deny(f"md-guard: {what} read in a shell without a column cap (long paragraph-lines "
             "blow the output). To locate, add `| cut -c1-300` "
             "(PowerShell: `| % { $_.Substring(0,[Math]::Min(300,$_.Length)) }`); it "
             "truncates long lines, so read the content itself with Read, not the shell. "
             + HOW + tail)


def main():
    try:
        # Explicit UTF-8, same as the other two hooks: sys.stdin uses the locale codec
        # (cp1252 on Windows) while the payload arrives from JSON.stringify with non-ASCII
        # left raw. Measured 2026-09-19: a 400-line .md under a path holding "ö" decoded
        # into a path that does not exist, line_count() returned 0, and the Read was
        # ALLOWED - the guard failing open exactly where the path is not ASCII.
        data = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    except Exception:
        return
    tool = data.get("tool_name", "")
    inp = data.get("tool_input", {}) or {}
    # /kit-off quiets the big-.md checks only. The read-only write guard below stays on in
    # every project: it is the one write boundary refuter and debugger have, and a marker any
    # shell can create must not be able to lift it (refuter-02, 2026-09-23: `python -c
    # "os.open('.claude/kit-off', os.O_CREAT)"` passed, and every later write went unguarded).
    off = kit_off()
    if tool == "Read":
        if not off:
            check_read(inp)
    elif tool in ("Bash", "PowerShell"):
        # `plugin:kit:refuter` is a refuter: the payload names the agent namespaced when the
        # agent comes from a plugin.
        agent_type = str(data.get("agent_type", "")).split(":")[-1]
        if agent_type in READ_ONLY_AGENTS:
            # the whole command string, not per `&&` segment: a write anywhere in it is a write
            write_re = BASH_WRITE_RE if tool == "Bash" else PS_WRITE_RE
            raw = inp.get("command", "")
            # the redirect rule alone reads the stripped command; every other shape (an
            # `open(` mode, an os.remove argument) lives INSIDE the quotes
            if write_re.search(raw) or REDIRECT_RE.search(_strip_quotes(raw)):
                deny(f"md-guard: {agent_type} is a read-only agent and this command writes "
                     "(a file, the tree, or a remote). Report the change you wanted "
                     "instead; the orchestrator files it.")
        if not off:
            check_bash(inp, data.get("cwd"), tool)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        pass
