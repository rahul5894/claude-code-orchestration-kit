"""PreToolUse guard (Bash and PowerShell): a big markdown doc is never dumped raw into a shell.

Read is left to Claude Code itself (2026-10-07, bucket kit-digest-review D005): its Read
returns a doc whole up to 25K tokens, pages a longer one with a PARTIAL-view note that names
the next offset and says not to answer from one page, and refuses one over 256 KB with "use
offset and limit". A shell has none of that - long paragraph-lines blow its output - so:
Bash  -> deny when cat/sed/awk/grep/rg/head/tail READ a .md path that resolves to a file over
         300 lines, with no column cap, and the read's real output is not known to fit
         OUTPUT_BUDGET (8000 chars): cat/head/tail/sed -n are computed exactly, a grep is run
         read-only, then head/tail/grep/sort/uniq stages applied; anything else is denied as
         before (bucket kit-optimize-pass D001). Writes (heredoc, redirect, sed -i, tee), counts
         and capped output pass. Shell spellings are expanded first (quoted or glued words,
         $VAR/${VAR}/$env:X from the env or the command's own assignments and for-loops,
         $(pwd), {a,b}, git rev:path, a bare name under a folder a file reader names); a grep's
         pattern, a URL and a path that resolves to nothing (a file the same command creates)
         pass: 64% of the shell denials since 09-29 were such paths or small files.
Bash/PowerShell -> deny outright when the payload's agent_type is a read-only
         agent and the command has a named write shape (redirect, sed -i, tee,
         rm/mv/cp, tree-changing git, a write-mode open(), a package install).
Exit 0 + JSON on stdout = decision. Any crash = allow (fail open, dev tool).
Self-check: python md-guard_test.py
"""
import os
import sys

# The hook's own folder, explicitly: under PYTHONSAFEPATH=1 (or python -P / -I) the script dir
# is not on sys.path, the import fails and the hook exits 1 - which fails open (refuter-02).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kit_off import kit_off  # noqa: E402

READ_ONLY_AGENTS = {"refuter", "debugger"}
# Most shell calls need no check at all: no read-only agent runs them, and either the kit is off
# here (the default) or the command names no `.md` and no `$` - the first test every segment's
# check makes (_segment_reads_big_md), here on the raw payload, which holds the command whole.
# Decided before the imports and the patterns below load: 40 -> ~23 ms a call (bucket
# kit-default-off-optimize, D003). Anything else falls through to the full check, so this can only
# skip work, never a guard.
_RAW = sys.stdin.buffer.read() if __name__ == "__main__" else b""
_OFF = __name__ == "__main__" and kit_off()
if (__name__ == "__main__" and not any(a.encode() in _RAW for a in READ_ONLY_AGENTS)
        and (_OFF or (b".md" not in _RAW.lower() and b"$" not in _RAW))):
    sys.exit(0)

import json  # noqa: E402
import re  # noqa: E402

MAX_LINES = 300
CAP_RE = re.compile(
    # `grep -l` is deliberately NOT here, though it prints file names only. Tried and
    # reverted 2026-09-19: `[^|]*` caps the REGEX, not the command, so
    # `grep -rl x --include=*.md . | xargs cat` matched and dumped every file, and the flag
    # pattern also matched inside a search string (`grep -rn "use -all mode" big.md`).
    # Both were allowed by that hunk and both print content. The one-token `| cut -c1-300`
    # in the deny message is the supported way through.
    # `grep -q` prints nothing at all: a loop of them over big docs was denied (2026-10-11, D001).
    r"cut -c|--max-columns|\s-o\s|\bwc\b|\b(?:grep|rg)\b[^|]*\s-c\b|\b(?:grep|rg)\b[^|]*\s(?:-q|--quiet)\b"
    r"|\.Substring\(|Measure-Object"
)
WRITE_RE = re.compile(
    r"<<|>\s*\"?[^|\s]*\.md\b|\bsed\s+-i|\bawk\s+-i|\btee\b", re.IGNORECASE
)
READERS = re.compile(
    r"\b(?:cat|sed|awk|grep|rg|head|tail|less|more"
    r"|Get-Content|gc|type|Select-String|sls)\b", re.IGNORECASE
)
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
# Before it, any commands ending in `;`, `&&` or `||` with no `<`, open quote or backtick: the body
# still goes to the heredoc's own cat/tee (`B=x && cat >> $B/FINDINGS.md <<'EOF'` and `cd x && rm
# -rf y; cat >> f <<'EOF'` were denied 2026-10-11). The head line is judged as before.
_CD = r"\s*(?:(?:\"_*\"|'_*'|[^<'\"`\n])*?(?:;|&&|\|\|)\s*)?"
HEREDOC_WRITE_RES = (
    re.compile(_CD + r"(?:cat\s*>>?\s*" + _TARGET + r"|tee\s+(?:-a\s+)?" + _TARGET + r")"
               r"\s+<<-?\s*(['\"])(\w+)\1\s*"),
    re.compile(_CD + r"cat\s+<<-?\s*(['\"])(\w+)\1\s*>>?\s*" + _TARGET + r"\s*"),
)

# A read-only agent's verdict is discarded whole if the tree moved under it, so the shell
# writes it can name are denied here rather than found afterwards in a git diff.
# A denylist of named write shapes; the prose prohibition and the git-status diff catch
# the rest. READ_ONLY_AGENTS is defined at the top, where the fast path reads it.
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
# kit_switch.py writes a project's rules copy (the kit's switch), settings.local.json and
# .git/info/exclude. (install\.ps1 matches uninstall.ps1 too.)
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


HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*#*\s*$")
# Characters of headings handed over with a shell denial: 4000 made one denial ~5 KB of context
# (OPI's DECISIONS.md); the rest is a `grep -n '^#'` away (kit-optimize-pass D001).
MAX_OUTLINE = 2000


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


def _local(p, base):
    """`p` as this machine spells it: ~ expanded, Git Bash /c/x as C:/x, relative under base."""
    p = p.replace("~", os.path.expanduser("~"))
    if p.startswith("/") and len(p) > 2 and p[2] == "/" and p[1].isalpha():
        p = p[1].upper() + ":" + p[2:]
    return p if os.path.isabs(p) else os.path.join(base, p)


def _resolve(raw, base):
    """The files `raw` names, as a list (a glob can name several), or None if none exist.
    Relative paths resolve against `base`: the payload cwd, moved by any `cd` before them."""
    cand = _local(raw, base)
    if any(c in cand for c in "*?["):
        import glob  # here, not at the top: ~5 ms of imports a wildcard alone needs
        return [h for h in glob.glob(cand) if os.path.isfile(h)] or None
    return [cand] if os.path.isfile(cand) else None


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


def _segment_reads_big_md(cmd, base, tool, env):
    """(path, lines) of the big .md file this segment reads raw - ("*.md", 0) for a recursive
    .md filter - else None. `env` is a callable: the variables are only collected when needed."""
    # A reader word ANYWHERE in the segment counts: judging only the command position let `<x.md
    # cat`, `find -exec cat`, `eval cat`, `bash -lc` and ~25 more shapes through (refuter,
    # 2026-09-29). Precision comes from the cases below, never from narrowing this.
    if ".md" not in cmd.lower() and "$" not in cmd or not READERS.search(cmd):
        return None
    if CAP_RE.search(cmd) or WRITE_RE.search(cmd):
        return None
    if _heading_search(cmd):
        return None
    if MD_OPTION.search(cmd):
        return "*.md", 0
    if tool == "Bash" and _lists_only(cmd):
        return None
    # Only a path that RESOLVES to a big file is gated, so the spellings a shell expands are
    # expanded first (review 2026-10-07: quoted paths with spaces, $(pwd), $env:X, {a,b}, a bare
    # "$f" from a loop all read big docs past a guard that took literal tokens only). What still
    # resolves to nothing - a search string, a file this command creates - reads nothing big.
    pattern = _search_pattern(cmd)
    spelled = [s for tok in _candidates(cmd, quoted_globs=tool != "Bash") for s in _spellings(tok, env(), base)
               if s != pattern and "://" not in s and not s.startswith(("//", "\\\\"))]
    # A bare name may sit in a folder the segment names (`find <dir> -name x.md -exec cat`,
    # `bash -c "cd docs && cat x.md"`, `Get-Content (Join-Path docs x.md)`) - joined only when a
    # FILE reader or find is there: a grep's pattern is text, not a file (review 2026-10-07).
    # A URL or UNC spelling is never resolved: isfile on //host/x took 17 s (refuter 12).
    dirs = ([d for s in spelled if len(s) > 1 and os.path.isdir(d := _local(s, base))][:10]
            if _FILE_READER.search(cmd) else [])
    for s in spelled:
        if ".md" not in s.lower():
            continue
        found = _resolve(s, base)
        if found is None and not (os.path.isabs(s) or s.startswith(("/", "~"))):
            found = next((r for d in dirs if (r := _resolve(os.path.join(d, s), base))), None)
        for f in found or []:
            n = line_count(f)
            if n > MAX_LINES:
                return f, n
    return None


_ASSIGN = re.compile(r"(?:^|[\s;&|(])([A-Za-z_]\w*)=(\"[^\"]*\"|'[^']*'|[^\s;&|]*)")
_FOR = re.compile(r"\bfor\s+([A-Za-z_]\w*)\s+in\s+([^;\n]*?)\s*;?\s*do\b")
# `$env:X` first: the plain form would read it as a variable named `env`.
_VAR = re.compile(r"\$env:([A-Za-z_]\w*)|\$\{?([A-Za-z_]\w*)\}?", re.IGNORECASE)
# One shell word: quoted and unquoted runs glued together (`"$(pwd)"/docs/x.md`, `docs/"x".md`).
_WORD = re.compile(r"(?:\"[^\"]*\"|'[^']*'|[^\s|<>;&\"'])+")
_PIECES = re.compile(r"[\s()`,=]+")
_SEARCH = re.compile(r"^\s*(?:grep|egrep|fgrep|rg|Select-String|sls)\b(.*)$", re.IGNORECASE | re.DOTALL)
_FILE_READER = re.compile(r"\b(?:cat|sed|awk|head|tail|less|more|Get-Content|gc|type|find)\b",
                          re.IGNORECASE)
# Flags that take a value, case-sensitive: grep's -a/-b/-c take none, -A/-B/-C do (verifier N2).
_VALUE_FLAGS = {"-g", "--glob", "-t", "--type", "-T", "--type-not", "-m", "--max-count", "-A", "-B",
                "-C", "--context", "-Path", "-path", "-LiteralPath"}
_BRACE = re.compile(r"\{([^{}]*,[^{}]*)\}")
_PWD = re.compile(r"\$\(\s*pwd\s*\)|`\s*pwd\s*`|\$\{?PWD\}?")


def _vars(cmd):
    """name -> [values]: the command's own `X=...` assignments and `for x in a b c` loop words,
    over the environment's (case-insensitive on Windows, as os.environ is). The full command,
    not one segment: an assignment before `&&` is still set in the segment that reads."""
    env = {k: [v] for k, v in os.environ.items()}
    for name, val in _ASSIGN.findall(cmd):
        env[name] = [val.strip("'\"")]
    for name, words in _FOR.findall(cmd):
        env[name] = [w.strip("'\"") for w in words.split()] or [""]
    return env


def _candidates(seg, quoted_globs=True):
    """Every token that may be a path: each shell word with its quotes removed (a path with
    spaces, glued quoting) and its pieces (a path inside `python -c '...'`). quoted_globs=False
    (bash): a path-like word whose wildcards all sit inside quotes names no file - bash passes
    `"*.md"` on as written (`git ls-files "*.md" | ...` was denied 2026-10-11)."""
    out = []
    for word in _WORD.findall(seg):
        inner = re.sub(r"[\"']", "", word)
        if len(inner) > 1000:
            continue
        if (not quoted_globs and re.fullmatch(r"[\w./\\*?\[\]~:-]+", inner) and any(c in inner for c in "*?[")
                and not any(c in _QUOTED.sub("", word) for c in "*?[")):
            continue
        out.append(inner)
        out += [p for p in _PIECES.split(inner) if p and p != inner]
    return out


def _search_pattern(seg):
    """The pattern of a grep/rg/Select-String segment: text searched for, not a file read
    (`grep -rn "README.md" docs` was denied when a README.md sat in the cwd; refuter 19)."""
    m = _SEARCH.match(seg)
    if not m:
        return None
    words = iter(re.sub(r"[\"']", "", w) for w in _WORD.findall(m.group(1)))
    for w in words:
        if w in ("-e", "--regexp") or w.lower() == "-pattern":
            return next(words, None)
        if w in ("-f", "--file"):
            return None  # patterns come from a file: every positional word is a file read
        if w.startswith("-"):
            if w in _VALUE_FLAGS:
                next(words, None)
            continue
        return w
    return None


# A heading search prints one line per markdown heading - the outline this guard prints with a
# denial anyway - so it passes whatever the file's size. project-records hands its agent exactly
# that as its index (`grep -n "^### " docs/DECISIONS.md`), and in a kit-ON records project every
# such call on a doc over 300 lines was denied, a turn lost each time (2026-10-11, bucket
# kit-records-integration). Only one pattern whose every alternative is anchored at `^#`, and no
# flag that prints other lines: context (-A/-B/-C, -NUM, --context) or an inverted match (-v).
_OTHER_LINES = re.compile(r"-[A-Za-z]*[ABCv][A-Za-z0-9]*|-\d+|--(?:after-|before-)?context(?:=\S*)?|--invert-match")
_PATTERN_FLAGS = ("-e", "--regexp", "-f", "--file", "-pattern")


def _first_stage(seg):
    """The segment up to its first pipe outside quotes."""
    quote = None
    for i, ch in enumerate(seg):
        if quote:
            quote = None if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch == "|":
            return seg[:i]
    return seg


def _heading_search(seg):
    stage = _first_stage(seg)
    m = _SEARCH.match(stage)
    if not m:
        return False
    words = [re.sub(r"[\"']", "", w) for w in _WORD.findall(m.group(1))]
    if sum(w.lower() in _PATTERN_FLAGS for w in words) > 1:
        return False  # a second pattern searches the body
    if any(_OTHER_LINES.fullmatch(w) or w.lower() in ("-context", "-notmatch") for w in words):
        return False
    pattern = _search_pattern(stage)
    return bool(pattern) and all(a.startswith("^#") for a in re.split(r"\\\||\|", pattern))


def _spellings(tok, env, base, depth=0):
    """Every spelling `tok` can take once the shell expands it: $(pwd)/`pwd`/$PWD, $VAR, ${VAR},
    $env:VAR, {a,b}, and a `git show rev:path` revision prefix. A variable with no known value
    stays as written (and then resolves to nothing)."""
    if depth > 4:
        return [tok]
    tok = _PWD.sub(lambda m: base.replace("\\", "/"), tok)
    m = _BRACE.search(tok)
    m2 = None if m else _VAR.search(tok)
    vals = (m.group(1).split(",") if m else
            m2 and (env.get(m2.group(1) or m2.group(2))
                    or (os.name == "nt" and env.get((m2.group(1) or m2.group(2)).upper()))))
    if vals:
        # Built lazily up to 40: six 20-way braces expanded whole took 0.78 s (refuter 13).
        at = m or m2
        out = []
        for v in vals[:20]:
            out += _spellings(tok[:at.start()] + v + tok[at.end():], env, base, depth + 1)
            if len(out) >= 40:
                break
        return out[:40]
    rev = re.match(r"^[^/\\:\s]{2,}:(.+)$", tok)
    return [tok, rev.group(1)] if rev else [tok]


# What a read of a big doc really prints, measured before a denial (bucket kit-optimize-pass D001):
# of ~467 denials in 30 days the next call was the same command + `| cut` 246 times - the
# denial spent a turn on `grep -n "D-044" DECISIONS.md` (3 short lines), `sed -n 10,20p`, `tail -c
# 400`. Output that fits OUTPUT_BUDGET passes; anything not computed exactly is denied as before.
OUTPUT_BUDGET = 8000  # characters, ~2K tokens
_SED_RANGE = re.compile(r"^(\d+)(?:,(\d+|\$))?p$")
_STDERR = re.compile(r"\s2>(?:/dev/null|&1)(?=\s|$)")


def _words(stage, base):
    """The stage's words exactly as bash hands them over, or None when bash would change one in a
    way not modelled here: a `$` or backtick outside single quotes, an unquoted brace, redirect,
    subshell, separator, `~` or backslash. An unquoted `*`/`?` word is expanded as bash does
    (sorted matches, the word itself when none). A stderr redirect (2>/dev/null, 2>&1) goes first."""
    stage = _STDERR.sub(" ", stage)
    words, cur, have, q, globby = [], [], False, None, False

    def flush():
        w = "".join(cur)
        if globby:
            import glob  # here, not at the top: only an unquoted wildcard needs it
            hits = sorted(glob.glob(_local(w, base)))
            if hits:
                return [h.replace("\\", "/") for h in hits]
        return [w]

    i = 0
    while i < len(stage):
        ch = stage[i]
        i += 1
        if q == "'":
            if ch == "'":
                q = None
            else:
                cur.append(ch)
        elif q == '"':
            if ch == '"':
                q = None
            elif ch in "$`":
                return None
            elif ch == "\\":
                # Inside double quotes a backslash escapes only $ ` " \ - `"a\|b"` keeps it.
                if i < len(stage) and stage[i] in '$`"\\':
                    cur.append(stage[i])
                    i += 1
                else:
                    cur.append(ch)
            else:
                cur.append(ch)
        elif ch in "'\"":
            q, have = ch, True
        elif ch.isspace():
            if cur or have:
                words += flush()
            cur, have, globby = [], False, False
        elif ch in "*?":
            globby = True
            cur.append(ch)
        elif ch in "$`[]{}<>()\\|;&~":
            return None
        else:
            cur.append(ch)
    if q:
        return None
    if cur or have:
        words += flush()
    return words


def _count_arg(words, i, flag_n="-n"):
    """(how, n) of a head/tail option list from index i on: ("lines"|"bytes"|"from", n)."""
    how, n, files = "lines", 10, []
    while i < len(words):
        w = words[i]
        if w in (flag_n, "-c", "--lines", "--bytes") and i + 1 < len(words):
            how, val = ("bytes" if w in ("-c", "--bytes") else "lines"), words[i + 1]
            if val.startswith("+"):
                how, val = ("from", val[1:]) if how == "lines" else (None, val)
            n = int(val) if val.isdigit() else -1
            i += 2
            continue
        if re.fullmatch(r"-\d+", w):
            n, i = int(w[1:]), i + 1
            continue
        if w.startswith("-"):
            return None  # an option this model does not know
        files.append(w)
        i += 1
    return (how, n, files) if how and n >= 0 else None


def _grep_exe(name):
    import shutil  # here, not at the top: only a measured grep needs it
    found = shutil.which(name)
    if found or name != "grep":
        return found
    git = shutil.which("git")  # exec-form hooks run without Git Bash's PATH: grep sits beside git
    if git:
        cand = os.path.join(os.path.dirname(os.path.dirname(git)), "usr", "bin", "grep.exe")
        return cand if os.path.isfile(cand) else None
    return None


def _first_output(stage, base):
    """The exact text the first pipeline stage prints, or None when it is not modelled."""
    words = _words(stage, base)
    if not words:
        return None
    prog = os.path.basename(words[0]).lower().removesuffix(".exe")
    if prog in ("grep", "egrep", "fgrep", "rg"):
        exe = _grep_exe(prog)
        if not exe:
            return None
        import subprocess  # here, not at the top: ~5 ms only a measured grep needs
        try:
            r = subprocess.run([exe] + words[1:], cwd=base, capture_output=True, timeout=2,
                               stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return r.stdout.decode("utf-8", "replace") if r.returncode in (0, 1) else None
    if prog == "cat" and len(words) == 2 and not words[1].startswith("-"):
        found = _resolve(words[1], base)
        if not found:
            return None
        with open(found[0], encoding="utf-8", errors="replace") as f:
            return f.read()  # whole: alone it is a dump, only a later head/tail can make it small
    if prog in ("head", "tail"):
        spec = _count_arg(words, 1)
        if not spec or len(spec[2]) != 1:
            return None
        how, n, (name,) = spec
        found = _resolve(name, base)
        if not found:
            return None
        with open(found[0], "rb") as f:
            data = f.read()
        if how == "bytes":
            return (data[:n] if prog == "head" else data[-n:] if n else b"").decode("utf-8", "replace")
        lines = data.decode("utf-8", "replace").splitlines(True)
        if how == "from":
            return "".join(lines[max(n - 1, 0):]) if prog == "tail" else None
        return "".join(lines[:n] if prog == "head" else (lines[-n:] if n else []))
    if prog == "sed" and len(words) == 4 and words[1] == "-n":
        # One range or several, `;`-separated (`93p;170p` was denied 2026-10-11): each prints its
        # lines; any other command in the script is not modelled.
        ms = [_SED_RANGE.match(x.strip()) for x in words[2].split(";")]
        found = _resolve(words[3], base) if all(ms) else None
        if not found:
            return None
        with open(found[0], encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines(True)
        out = []
        for m in ms:
            a = int(m.group(1))
            b = a if not m.group(2) else (len(lines) if m.group(2) == "$" else int(m.group(2)))
            out.append("".join(lines[a - 1:b]))
        return "".join(out)
    return None


def _small_output(seg, base):
    """True when the segment's whole output is known and fits OUTPUT_BUDGET: its first stage
    computed exactly, then each later stage a head/tail or a filter over it (grep, sort, uniq,
    wc, tr, cut, awk, sed - taken to print no more than they read) that names no .md of its own."""
    stages = _scan(seg, stages=True)
    if not stages:
        return False
    text = _first_output(stages[0].strip(), base)
    if text is None:
        return False
    for st in stages[1:]:
        words = _words(st, base) or []
        prog = os.path.basename(words[0]).lower() if words else ""
        if prog in ("head", "tail"):
            spec = _count_arg(words, 1)
            if not spec or spec[2] or spec[0] not in ("lines", "bytes"):
                return False
            if spec[0] == "bytes":  # `| head -c 120`: a byte cap (measured live 2026-10-11, denied)
                data = text.encode("utf-8")
                data = data[:spec[1]] if prog == "head" else (data[-spec[1]:] if spec[1] else b"")
                text = data.decode("utf-8", "replace")
                continue
            lines = text.splitlines(True)
            text = "".join(lines[:spec[1]] if prog == "head" else (lines[-spec[1]:] if spec[1] else []))
        elif prog.removesuffix(".exe") in ("grep", "egrep", "fgrep", "rg", "sort", "uniq", "wc", "tr",
                                           "cut", "awk", "gawk", "sed"):
            # Over stdin (`| awk -F'|' '{print NF}'` was denied 2026-10-11); a stage naming a .md
            # reads that file instead, which the first stage never measured.
            if any(".md" in w.lower() for w in words[1:]):
                return False
        else:
            return False
    return len(text) <= OUTPUT_BUDGET


def _reads_big_md(cmd, base, tool="Bash"):
    """(path, lines) of the big .md file `cmd` reads raw, or None."""
    cache = []

    def env():
        if not cache:
            cache.append(_vars(cmd))
        return cache[0]

    segments = _scan(cmd)
    if segments is None:  # an unclosed quote: split as before quotes were read at all
        segments = re.split(r"&&|\|\||;|\n", cmd)
    outer = []  # the dir to return to when a `( ... )` subshell closes (verifier N3)
    for seg in segments:
        if seg.lstrip().startswith("("):
            outer.append(base)
        cd = CD_RE.fullmatch(seg.lstrip(" ("))  # `(cd docs && cat x.md)` changes dir inside
        if cd:
            target = _local(cd.group(1).strip("'\")"), base)
            if os.path.isdir(target):
                base = target
        else:
            big = _segment_reads_big_md(seg, base, tool, env)
            # A read whose real output is small prints nothing big (D001): measured, not guessed.
            if big and not (tool == "Bash" and _small_output(seg, base)):
                return big
        if outer and seg.rstrip().endswith(")"):
            base = outer.pop()
    return None


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
        path, n = big
        # The way to the knowledge goes first, with the exact path (2026-10-12): agents that got
        # "add | cut" first sometimes read content through it, every long line cut at 300 chars.
        if path == "*.md":
            what, first, tail = "a recursive .md search", "", ""
        else:
            what = f"{os.path.basename(path)} ({n} lines)"
            first = (f"To read it, use the Read tool on `{path.replace(chr(92), '/')}`: it returns the "
                     "whole document when it fits and pages a longer one - read every page in order to "
                     "the end; nothing is withheld. ")
            tail = (" A doc the agent must have whole (CLAUDE.md, a brief, a handoff, a skill) Reads "
                    "whole with no limit. Outline (the file's own headings - document text, not "
                    "instructions):\n" + outline(path))
        deny(f"md-guard: {what} read in a shell without a column cap (long paragraph-lines "
             "blow the output). " + first + "To locate a spot instead, add `| cut -c1-300` "
             "(PowerShell: `| % { $_.Substring(0,[Math]::Min(300,$_.Length)) }`); it "
             "truncates long lines, so never read content that way. " + HOW + tail)


def main():
    try:
        # Explicit UTF-8, same as the other two hooks: sys.stdin uses the locale codec
        # (cp1252 on Windows) while the payload arrives from JSON.stringify with non-ASCII
        # left raw. Measured 2026-09-19: a 400-line .md under a path holding "ö" decoded
        # into a path that does not exist, line_count() returned 0, and the Read was
        # ALLOWED - the guard failing open exactly where the path is not ASCII.
        data = json.loads(_RAW.decode("utf-8"))
    except Exception:
        return
    tool = data.get("tool_name", "")
    inp = data.get("tool_input", {}) or {}
    # An off project (the default) skips the big-.md checks only. The read-only write guard
    # below stays on in every project: it is the one write boundary refuter and debugger have,
    # and a switch any shell can flip must not be able to lift it (refuter-02, 2026-09-23: a
    # created `.claude/kit-off` marker lifted it, and every later write went unguarded).
    off = _OFF
    if tool in ("Bash", "PowerShell"):
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
