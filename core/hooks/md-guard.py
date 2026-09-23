"""PreToolUse guard: big markdown docs are read in windows, never raw Read/cat whole.

Read  -> deny when a .md file has >300 lines and no limit<=300 is given.
Bash  -> deny when cat/sed/awk/grep/rg/head/tail READ a .md path that is big
         (or cannot be resolved) with no column cap. Writes (heredoc, redirect,
         sed -i, tee), counts and capped output pass.
Bash/PowerShell -> deny outright when the payload's agent_type is a read-only
         agent and the command has a named write shape (redirect, sed -i, tee,
         rm/mv/cp, tree-changing git, a write-mode open(), a package install).
Exit 0 + JSON on stdout = decision. Any crash = allow (fail open, dev tool).
Self-check: python md-guard_test.py
"""
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
_CD = r"\s*(?:cd\s+" + _PATH + r"\s*&&\s*)?"
HEREDOC_WRITE_RES = (
    re.compile(_CD + r"(?:cat\s*>>?\s*" + _PATH + r"|tee\s+(?:-a\s+)?" + _PATH + r")"
               r"\s+<<-?\s*(['\"])(\w+)\1\s*"),
    re.compile(_CD + r"cat\s+<<-?\s*(['\"])(\w+)\1\s*>>?\s*" + _PATH + r"\s*"),
)

# A read-only agent's verdict is discarded whole if the tree moved under it, so the shell
# writes it can name are denied here rather than found afterwards in a git diff.
# ponytail: denylist of named write shapes; the prose prohibition and the git-status diff
# catch the rest
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
HOW = ("Find the spot with `grep -n \"<anchor>\" <file> | cut -c1-300`, then Read with "
       "offset+limit.")


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


def check_read(inp):
    path = inp.get("file_path", "")
    if not path.lower().endswith(".md"):
        return
    n = line_count(path)
    if n <= MAX_LINES:
        return
    limit = inp.get("limit")
    if isinstance(limit, int) and limit <= MAX_LINES:
        return
    deny(f"md-guard: {os.path.basename(path)} has {n} lines (>{MAX_LINES}). "
         f"Do not Read it whole. {HOW}")


def _resolve(raw):
    raw = raw.replace("~", os.path.expanduser("~"))
    for cand in (raw, os.path.join(os.getcwd(), raw)):
        if os.path.isfile(cand):
            return cand
    if raw.startswith("/") and len(raw) > 3 and raw[2] == "/":  # /d/x -> D:/x
        cand = raw[1].upper() + ":" + raw[2:]
        if os.path.isfile(cand):
            return cand
    return None


def _segment_reads_big_md(cmd):
    paths = MD_PATH.findall(cmd)
    if not paths or not READERS.search(cmd):
        return False
    if CAP_RE.search(cmd) or WRITE_RE.search(cmd):
        return False
    # small files are fine to read raw; only big (or unresolvable) ones are gated
    resolved = [_resolve(p) for p in paths]
    return not all(r and line_count(r) <= MAX_LINES for r in resolved)


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


def check_bash(inp):
    # Bodies go for this READ check only. Write detection in main() reads the raw command,
    # or `bash <<EOF` would hide any write inside its body (D007).
    cmd = _strip_heredocs(inp.get("command", ""))
    # judge each `a && b ; c || d` segment on its own: `rm x.md && git status | head`
    # must not trip on the `head` of an unrelated segment
    for seg in re.split(r"&&|\|\||;|\n", cmd):
        if _segment_reads_big_md(seg):
            deny("md-guard: reading a .md file in a shell without a column cap "
                 "(long paragraph-lines blow the output). Add `| cut -c1-300` "
                 "(PowerShell: `| % { $_.Substring(0,[Math]::Min(300,$_.Length)) }`). " + HOW)


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
            check_bash(inp)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        pass
