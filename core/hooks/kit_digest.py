"""Session digest: what was SAID in a session, word for word, without what the repo holds.

kit-context.py writes it into the handoff's own bucket - <bucket>/digests/<session>.md, the
bucket whose STATE.md this session wrote last - on every stop after its Stop block, so it is
current to the last turn before /clear; kit_chain.py writes it for every other session that
touched a bucket, at any context %, when the session ends (bucket handoff-timeline). /continue
reads the newest whole. STATE.md is the curated snapshot the model
writes; this is the deterministic record beside it: every user message verbatim, every answer
the model gave, the tool trail, output excerpts, errors and refusals as seen, subagent reports.
No model call. Nothing here deletes a digest: kit_chain.prune() does, 7 days after the bucket
closes (the user's rule, 2026-10-09; the old keep-the-newest-5 cap lost S1-S4 of 9-session tasks).

Why verbatim (bucket kit-2.1.292-optimize, F8 and F13): in four studies text copied word for
word beat LLM-written summaries, and on 4 real handoffs STATE.md alone let a cold reader answer
63.4% of what the next session needed, STATE.md + this digest 94.7%. Tool output is ~84% of a
transcript and re-readable (files are on disk), so leaving most of it out is the compression.

Size: BANDS is the user's table (2026-10-07) - by how full the session was, the digest may take
10-30% of the window and STATE.md 60-120 lines. The share is a ceiling, never a target. Over
it, the oldest turns lose detail first (tool output, then narration, a folded tool trail and cut
answers); user messages and the newest TAIL turns are never cut.

    python kit_digest.py <transcript.jsonl> [--upto-line N] [--pct P --window W] [--out f.md]
"""
import json
import os
import re
import sys
import time
from collections import Counter

TAIL = 6                 # newest turns kept whole, whatever the cap
CHARS_PER_TOKEN = 4      # estimate; the reader only needs an order of magnitude
AGENT_CHARS = 6000       # a subagent report
CUT_CHARS = 700          # an old answer or report, once the cap bites
ERROR_CHARS = 400
CMD_CHARS = 200
CALL_CHARS = 160         # the failing call named on an error line
NOTICE_CHARS = 1500      # a background task's completion notice, once the cap bites
OUT_CHARS = 600          # a tool output excerpt: a shell's tail, a search's or web tool's head
SHELLS = ("Bash", "PowerShell")
FILE_TOOLS = ("Read", "Edit", "Write", "NotebookEdit", "MultiEdit")
WRITE_TOOLS = FILE_TOOLS[1:]
MAX_FILES = 80           # paths named in the header's files-changed line
AGENTS = ("Agent", "Task")
# Tools whose output is the file itself (on disk), a report kept apart, or bookkeeping.
NO_OUTPUT = set(FILE_TOOLS) | set(AGENTS) | {"TodoWrite", "Skill", "ToolSearch", "TaskStop",
                                             "ScheduleWakeup"}
# (context % below which the band applies, STATE.md lines, digest share of the window)
BANDS = ((50, 60, 0.10), (60, 60, 0.12), (70, 80, 0.18), (80, 100, 0.25), (10 ** 9, 120, 0.30))

# What the harness puts in the user's turn: a background task's or agent's completion and the
# interrupt marker. Never the user's words - measured 2026-10-10 over 544 transcripts: 577
# `<task-notification>` lines beside 2,045 typed messages, and one became a timeline's "asked".
HARNESS_USER = ("<task-notification>", "[Request interrupted")
NOTICE_SUMMARY = re.compile(r"<summary>(.*?)</summary>", re.DOTALL)
NOTICE_RESULT = re.compile(r"<result>(.*?)</result>", re.DOTALL)
# Inputs that say what an MCP or other tool call did, first found wins: an ssh MCP's `cmdString`
# is its whole command (747 of one task's server commands showed as a bare tool name).
CALL_KEYS = ("command", "cmdString", "cmd", "script", "sql", "code", "url", "query", "file_path",
             "path", "pattern", "prompt", "name")
NOISE = re.compile(r"<system-reminder>.*?</system-reminder>|<ide_opened_file>.*?</ide_opened_file>"
                   r"|<command-message>.*?</command-message>|<local-command-caveat>.*?"
                   r"</local-command-caveat>", re.DOTALL)
CMD_NAME = re.compile(r"<command-name>\s*(.*?)\s*</command-name>", re.DOTALL)
CMD_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)
STDOUT = re.compile(r"<local-command-stdout>(.*?)</local-command-stdout>", re.DOTALL)
SELECTION = re.compile(r"<ide_selection>(.*?)</ide_selection>", re.DOTALL)
# Secrets a user may paste into chat or a command may print: a key in a handoff is a key on disk
# in one more place. The NAME=value form matches from the key word on (EXA_API_KEY keeps `EXA_`):
# a leading `[\w-]*` retried at every character and cost 633 ms on 2.3M chars (review).
SECRET = re.compile(r"\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{16,}|fc-[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{20,}"
                    r"|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}"
                    r"|AIza[0-9A-Za-z_-]{30,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})")
# A *token* value with no letter is a count, not a secret: `max_tokens=200000` and
# "cache_read_input_tokens": 123456 are this kit's measurements (refuter 7). A password, secret or
# API key is redacted whatever it holds, digits only included (verifier N1). `pwd` is a path.
KEYVAL = re.compile(r"(?i)((?:api[_-]?key|secret|password|passwd)[A-Za-z0-9_-]*"
                    r"[\"']?\s*[=:]\s*[\"']?)[^\s'\",}]{4,}"
                    r"|(token[A-Za-z0-9_-]*[\"']?\s*[=:]\s*[\"']?)(?=[^\s'\",}]*[A-Za-z])[^\s'\",}]{4,}"
                    r"|(\b(?:Bearer|Basic)\s+)[A-Za-z0-9._~+/=-]{12,}")
URL_CREDS = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s:/@]+:)[^\s@/]+(?=@)", re.IGNORECASE)
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                         re.DOTALL)


def local_time(ts, fmt="%H:%M"):
    """A transcript timestamp (UTC ISO, `...Z`) in this machine's local time; the raw HH:MM when
    it does not parse. The turn headers once showed UTC beside a local `Written:` line, 5h30 off
    for an IST user (bucket handoff-timeline)."""
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone().strftime(fmt)
    except (ValueError, OSError, OverflowError):
        return str(ts)[11:16]


def budget(pct):
    """(STATE.md lines, digest share of the window) for a handoff at `pct`% context."""
    return next((lines, share) for top, lines, share in BANDS if pct < top)


def cap_tokens(pct, window):
    return int(budget(pct)[1] * window)


def redact(text):
    text = PRIVATE_KEY.sub("[redacted private key]", text)
    text = SECRET.sub("[redacted]", text)
    text = URL_CREDS.sub(lambda m: m.group(1) + "[redacted]", text)
    return KEYVAL.sub(lambda m: (m.group(1) or m.group(2) or m.group(3)) + "[redacted]", text)


def _blocks_text(content, keep_images=True):
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text":
            out.append(b.get("text") or "")
        elif b.get("type") == "image" and keep_images:
            out.append("[image]")
    return "\n".join(out)


def clean_user(text):
    """A typed prompt without the harness's wrappers; a slash command as `/name args`."""
    name = CMD_NAME.search(text)
    if name:
        args = CMD_ARGS.search(text)
        return (name.group(1) + " " + (args.group(1).strip() if args else "")).strip()
    if STDOUT.search(text) and not NOISE.sub("", STDOUT.sub("", text)).strip():
        return ""  # a local command's output only (/context, /cost): no words of the user's
    text = SELECTION.sub(lambda m: "[IDE selection: " + m.group(1).strip()[:300] + "]", text)
    return NOISE.sub("", text).strip()


def _one_line(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n] + "..."


def tool_line(name, inp):
    """One line naming what a tool call did: its target, never its output. Redacted before
    the cut: a key cut below its pattern's length would keep its first characters (refuter 9)."""
    inp = {k: redact(v) if isinstance(v, str) else v for k, v in (inp if isinstance(inp, dict) else {}).items()}
    if name in FILE_TOOLS:
        p = inp.get("file_path") or inp.get("notebook_path") or ""
        rng = (f" [{inp.get('offset', 1)}+{inp['limit']}]" if inp.get("limit") else "")
        return f"{name} {p}{rng}"
    if name in SHELLS:
        return f"{name}: {_one_line(inp.get('command', ''), CMD_CHARS)}"
    if name in ("Grep", "Glob"):
        return f"{name} {_one_line(inp.get('pattern', ''), 80)} {inp.get('path', '')}".rstrip()
    if name in AGENTS:
        return f"Agent {inp.get('subagent_type', '')}: {_one_line(inp.get('description', ''), 100)}"
    if name == "Skill":
        return f"Skill {inp.get('skill', '')} {_one_line(inp.get('args', ''), 100)}".rstrip()
    for k in CALL_KEYS:
        if isinstance(inp.get(k), str) and inp[k]:
            return f"{name} {_one_line(inp[k], CMD_CHARS if k in CALL_KEYS[:6] else 120)}"
    return name


def harness_text(text):
    """A user-turn line the harness wrote (HARNESS_USER), not the user."""
    return str(text).lstrip().startswith(HARNESS_USER)


def notice_text(text):
    """A `<task-notification>` as its summary line and result, the XML wrapper dropped."""
    s, r = NOTICE_SUMMARY.search(text), NOTICE_RESULT.search(text)
    if not s and not r:
        return text.strip()
    return ((s.group(1).strip() if s else "") + ("\n" + r.group(1).strip() if r else "")).strip()


def _excerpt(name, text):
    """What of a tool's output is kept: a shell's last lines (results print last), anything
    else's first; redacted before the cut, so a key whose prefix falls outside is still caught."""
    body = " ".join(redact(text).split())
    if len(body) <= OUT_CHARS:
        return body
    return "..." + body[-OUT_CHARS:] if name in SHELLS else body[:OUT_CHARS] + "..."


def extract(path, upto_line=None):
    """Turns of the main conversation, oldest first: each {'at', 'line', 'items', 'outs'}. An
    item is (kind, text, line), kind in user/text/tool/error/refused/agent/compact; `outs` maps a
    tool item's index to its output excerpt. Every text is redacted here, once."""
    turns, cur = [], None
    pending = {}  # tool_use_id -> (name, index of its tool item in cur["items"], its tool line)
    seen_user, seen_text = set(), set()

    def turn(at, n):
        nonlocal cur
        cur = {"at": local_time(at), "line": n, "items": [], "outs": {}}
        turns.append(cur)

    def add_user(text, at, n, new):
        key = " ".join(text.split())
        if key in seen_user and len(key) > 20:
            return  # the same long message pasted again adds nothing
        seen_user.add(key)
        if new or cur is None:
            turn(at, n)
        cur["items"].append(("user", redact(text), n))

    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return []
    with f:
        for n, raw in enumerate(f, 1):
            if upto_line and n > upto_line:
                break
            if '"isSidechain":true' in raw:
                continue
            try:
                o = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(o, dict) or o.get("isSidechain"):
                continue
            at = str(o.get("timestamp") or "")  # made local only where a turn starts: cheap
            kind = o.get("type")
            msg = o.get("message") or {}
            if kind == "attachment":
                a = o.get("attachment") or {}
                if a.get("type") == "queued_command":
                    t = clean_user(_blocks_text(a.get("prompt")))
                    if t.startswith("<task-notification>"):
                        # most notices land here: a background task ended while a turn ran
                        if cur is None:
                            turn(at, n)
                        cur["items"].append(("notice", redact(notice_text(t)), n))
                    elif t:
                        add_user(t, at, n, new=False)  # typed while a turn ran: part of it
                continue
            if kind == "user":
                content = msg.get("content")
                if o.get("isCompactSummary"):
                    if cur is None:
                        turn(at, n)
                    cur["items"].append(("compact", redact(_blocks_text(content)), n))
                    continue
                if isinstance(content, list) and any(
                        isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                    for b in content:
                        if not isinstance(b, dict) or b.get("type") != "tool_result" or cur is None:
                            continue
                        name, idx, call = pending.pop(b.get("tool_use_id"), ("", -1, ""))
                        text = _blocks_text(b.get("content"), keep_images=False)
                        if b.get("is_error") and "doesn't want to proceed" in text:
                            # A refusal is the user's: what they said with it is a user
                            # message, kept whole ("[rejected]" from git is no refusal).
                            said = text.split("the user said:", 1)[1].strip() if \
                                "the user said:" in text else ""
                            cur["items"].append(("refused", name + ("" if said else " (no words given)"), n))
                            if said:
                                cur["items"].append(("user", redact(said), n))
                        elif b.get("is_error"):
                            # The call goes with its error: on its own, "Exit code 49 Python was
                            # not found" let a reader name the wrong command (python for python3,
                            # step-back A/B round 3, the one confident wrong answer).
                            cur["items"].append(("error", f"{_one_line(call or name, CALL_CHARS)} -> "
                                                 f"{_one_line(redact(text), ERROR_CHARS)}", n))
                        elif name in AGENTS and text.strip().startswith("Async agent launched"):
                            continue  # a receipt: the report comes later, as a task notification
                        elif name in AGENTS and text.strip():
                            cur["items"].append(("agent", redact(text.strip()), n))
                        elif name and name not in NO_OUTPUT and text.strip() and idx >= 0:
                            cur["outs"][idx] = _excerpt(name, text)  # beside its own call
                    continue
                if o.get("isMeta"):
                    continue
                t = clean_user(_blocks_text(content))
                if t.startswith("<task-notification>"):
                    # It wakes the model as a message would: a turn of its own, so the cap can
                    # still fold a long run of them - but the harness's, never the user's words.
                    turn(at, n)
                    cur["items"].append(("notice", redact(notice_text(t)), n))
                elif t:
                    add_user(t, at, n, new=True)
                continue
            if kind == "assistant" and cur is not None:
                for b in msg.get("content") or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text" and (b.get("text") or "").strip():
                        t = b["text"].strip()
                        # Only a long text said twice is a repeat; a short "Done." ends many
                        # turns and each one says whether ITS turn finished.
                        if len(t) > 200 and t in seen_text:
                            continue
                        seen_text.add(t)
                        cur["items"].append(("text", redact(t), n))
                    elif b.get("type") == "tool_use":
                        line = tool_line(b.get("name", ""), b.get("input"))
                        cur["items"].append(("tool", line, n))
                        pending[b.get("id")] = (b.get("name", ""), len(cur["items"]) - 1, line)
    return turns


def _cut(body, line, what, keep=CUT_CHARS):
    if len(body) <= keep:
        return body
    return body[:keep] + f"\n[... {what} cut, {len(body) - keep} chars more at line {line}]"


def _render_turn(i, t, level):
    """One turn as markdown. Level 0 = whole; 1 = no tool output; 2 = the user's words, a
    folded tool trail and the answer and reports cut (narration dropped)."""
    texts = [k for k, it in enumerate(t["items"]) if it[0] == "text"]
    last = texts[-1] if texts else -1
    out = [f"### Turn {i} - {t['at']} (transcript line {t['line']})"]
    tools, files = [], []
    for k, (kind, text, line) in enumerate(t["items"]):
        if kind == "user":
            out.append("**User:**\n" + "\n".join("> " + x for x in text.splitlines()))
        elif kind == "compact":
            out.append(f"**Earlier compaction summary (line {line}):**\n{text}")
        elif kind == "tool":
            excerpt = t["outs"].get(k)
            tools.append(text + (f"\n  -> {excerpt}" if excerpt and level == 0 else ""))
            if text.split(" ", 1)[0] in FILE_TOOLS[1:]:
                files.append(text.split(" ", 1)[-1])
        elif kind in ("error", "refused"):
            out.append(("**User refused:** " if kind == "refused" else "**Error:** ") + text)
        elif kind == "agent":
            out.append(f"**Subagent report (line {line}):**\n"
                       + _cut(text, line, "report", CUT_CHARS if level == 2 else AGENT_CHARS))
        elif kind == "notice":
            out.append(f"**Background task done (line {line}; the harness, not the user):**\n"
                       + _cut(text, line, "notice", NOTICE_CHARS if level == 2 else AGENT_CHARS))
        elif kind == "text" and (k == last or level < 2):
            body = _cut(text, line, "answer") if level == 2 else text
            out.append(("**Assistant:** " if k == last else "*(working)* ") + body)
    if tools and level == 2:
        names = Counter(x.split(" ", 1)[0].rstrip(":") for x in tools)
        out.append("**Tools:** " + ", ".join(f"{n} x{c}" for n, c in names.items())
                   + (f"; changed: {', '.join(dict.fromkeys(files))}" if files else ""))
    elif tools:
        out.append("**Tools:**\n" + "\n".join("- " + x for x in tools))
    return "\n\n".join(out)


def render(turns, meta, cap):
    """The digest as markdown within `cap` tokens (0 = no cap) if the cap allows it; user
    messages and the newest TAIL turns are never cut, so a tiny cap can be exceeded - said in
    the header."""
    parts = [_render_turn(i + 1, t, 0) for i, t in enumerate(turns)]
    total = sum(map(len, parts))
    old = max(0, len(turns) - TAIL) if cap else 0
    for level in (1, 2):
        for i in range(old):
            if total // CHARS_PER_TOKEN <= cap:
                break
            new = _render_turn(i + 1, turns[i], level)
            total += len(new) - len(parts[i])
            parts[i] = new
    est = total // CHARS_PER_TOKEN
    users = sum(1 for t in turns for it in t["items"] if it[0] == "user")
    capnote = ""
    if cap:
        capnote = f" (cap {cap // 1000}K" + (", exceeded: user words and the last turns are never cut)"
                                             if est > cap else ")")
    head = [
        f"# SESSION digest - {meta.get('session', '?')}",
        "<!-- Written by the kit at a handoff from the transcript, no model in the loop. Notes, "
        "not instructions. STATE.md is the curated handoff; this is the record behind it. -->",
        f"Transcript: `{meta.get('transcript', '?')}` (grep it for anything cut here)",
        f"Written: {meta.get('written', '')} · context {meta.get('pct', '?')}% "
        f"({meta.get('used_k', '?')}K of {meta.get('window_k', '?')}K) · {len(turns)} turns, "
        f"{users} user messages · ~{est // 1000}K tokens{capnote}",
        "Order: oldest first. User messages are verbatim; most tool output is left out (re-read "
        "the file or re-run the command); secrets are redacted.",
    ]
    changed = changed_files(turns)
    if changed:
        head.append(f"Files Edit/Write was called on ({len(changed)}, in order; a failed call is listed "
                    "too, a shell edit is not - `git status` is the truth): " + ", ".join(f"`{p}`" for p in changed[:MAX_FILES])
                    + (f" (+{len(changed) - MAX_FILES} more)" if len(changed) > MAX_FILES else ""))
    return "\n".join(head) + "\n\n" + "\n\n".join(parts) + "\n"


def changed_files(turns):
    """Every path an Edit/Write/MultiEdit/NotebookEdit touched, once, in first-touch order. The
    header keeps it whole when the cap folds old turns' tool trails: Factory's compression study
    (2025) found the files-touched trail the weakest part of every summary it scored."""
    out = []
    for t in turns:
        for kind, text, _ in t["items"]:
            name, _, path = text.partition(" ") if kind == "tool" else ("", "", "")
            if name in WRITE_TOOLS and path and path not in out:
                out.append(path)
    return out


def ensure_folder(folder):
    """Create the digests folder - its last component only, inside a bucket that exists: a
    writer must never bring back a bucket that was renamed or moved to _closed/ (an existing
    folder makes an index row count as open). It gets a `*` .gitignore so nothing in it is ever
    committed. False when the parent is gone."""
    if not os.path.isdir(folder):
        if not os.path.isdir(os.path.dirname(folder)):
            return False
        try:
            os.mkdir(folder)
        except FileExistsError:
            pass
    ignore = os.path.join(folder, ".gitignore")
    if not os.path.lexists(ignore):  # a committed .gitignore symlink is never followed
        with open(ignore, "w", encoding="utf-8") as f:
            f.write("# Session digests hold the conversation verbatim: never commit them.\n*\n")
    return True


def write_atomic(path, text):
    """Whole file or the old one, never half: a tmp name of this process's own, then a rename.
    Two hooks writing the same digest at once (a SessionEnd and a repair) each use their own
    tmp; a rename that a reader's open handle blocks on Windows is retried once."""
    tmp = f"{path}.{os.getpid()}.{time.monotonic_ns() % 10 ** 9}.tmp"
    with open(tmp, "x", encoding="utf-8", newline="\n") as f:
        f.write(text)
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


def write(transcript, out_path, meta, cap, turns=None):
    """Write the digest of `turns` (default: the whole transcript). Returns the estimated
    tokens written, or -1 when there was nothing to write or the bucket is gone."""
    if turns is None:
        turns = extract(transcript)
    if not turns or not ensure_folder(os.path.dirname(out_path)):
        return -1
    text = render(turns, dict(meta, transcript=transcript, written=time.strftime("%Y-%m-%d %H:%M")), cap)
    write_atomic(out_path, text)
    return len(text) // CHARS_PER_TOKEN


def main(argv):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--upto-line", type=int)
    ap.add_argument("--pct", type=int, default=0)
    ap.add_argument("--window", type=int, default=1_000_000)
    ap.add_argument("--cap", type=int, help="tokens; default from --pct (0 = no cap)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    cap = a.cap if a.cap is not None else (cap_tokens(a.pct, a.window) if a.pct else 0)
    text = render(extract(a.transcript, a.upto_line), {"session": os.path.basename(a.transcript),
                                                       "pct": a.pct, "transcript": a.transcript,
                                                       "window_k": a.window // 1000}, cap)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
