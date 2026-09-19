"""PreToolUse guard: big markdown docs go through qmd, never raw Read/cat.

Read  -> deny when a .md file has >300 lines and no limit<=300 is given.
Bash  -> deny when cat/sed/awk/grep/rg/head/tail READ a .md path that is big
         (or cannot be resolved) with no column cap. Writes (heredoc, redirect,
         sed -i, tee), qmd calls, counts and capped output pass.
Exit 0 + JSON on stdout = decision. Any crash = allow (fail open, dev tool).
Self-check: python md-guard_test.py
"""
import json
import os
import re
import sys

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

HOW = (
    "Fuzzy lookup: `qmd update && qmd search \"<query>\" -c <collection> "
    "--full-path -n 5` then `qmd get \"<path>:<line>:<count>\"`. "
    "Exact anchor: `grep -n \"<anchor>\" <file> | cut -c1-300` then Read with "
    "offset+limit. Collections: `qmd collection list`; new repo: "
    "`qmd collection add <docs-dir> --name <repo>`."
)


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


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


def check_bash(inp):
    cmd = inp.get("command", "")
    # judge each `a && b ; c || d` segment on its own: `rm x.md && git status | head`
    # must not trip on the `head` of an unrelated segment
    for seg in re.split(r"&&|\|\||;|\n", cmd):
        if _segment_reads_big_md(seg):
            deny("md-guard: reading a .md file in a shell without a column cap "
                 "(long paragraph-lines blow the output). Add `| cut -c1-300` "
                 "(PowerShell: `| % { $_.Substring(0,[Math]::Min(300,$_.Length)) }`), "
                 "or use qmd. " + HOW)


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
    if tool == "Read":
        check_read(inp)
    elif tool in ("Bash", "PowerShell"):
        check_bash(inp)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        pass
