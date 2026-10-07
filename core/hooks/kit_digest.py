"""Session digest: what was SAID in a session, word for word, without what the repo holds.

kit-context.py writes it at a handoff into .claude/scratch/_sessions/<session-id>.md and names
it in the Stop block, so STATE.md can point at it and /continue reads it. STATE.md is the
curated snapshot the model writes; this is the deterministic record beside it: every user
message verbatim, every answer the model gave, the tool trail without tool outputs (files and
commands are on disk and in git), errors and refusals as seen, subagent reports. No LLM call.

Why verbatim and not a summary (FINDINGS F8, 2026-10-07): in four independent studies text
copied word for word beat LLM-rewritten summaries, and the losses that hurt a resumed session
are exact words - the user's instructions, numbers, paths. Tool outputs are ~84% of a coding
transcript and re-readable, so dropping them is most of the compression.

Size: `cap_tokens(pct, window)` is the user's table (2026-10-07) - a session handed off at
60-70% may keep up to 18% of the window, 70-80% 25%, 80%+ 30%, less below 60%. It is a
ceiling, never a target: nothing is padded. Over the cap, the oldest turns lose detail first
(narration, then the tool trail, then long answers are cut with a pointer to the transcript
line); user messages and the last TAIL turns are never cut.

    python kit_digest.py <transcript.jsonl> [--upto-line N] [--pct P --window W] [--out f.md]
"""
import json
import os
import re
import sys
import time

TAIL = 6                 # newest turns kept whole, whatever the cap
CHARS_PER_TOKEN = 4      # estimate; the reader only needs an order of magnitude
AGENT_REPORT_CHARS = 6000
ERROR_CHARS = 400
CMD_CHARS = 200
CUT_ANSWER_CHARS = 700
# Tool output is ~84% of a transcript and mostly re-readable (files are on disk), but a measured
# number often lives only in a command's output: shells keep their last lines, searches and web
# tools their first. Read/Edit/Write keep nothing - the file is there to read again.
OUT_TAIL = {"Bash": 600, "PowerShell": 600}
OUT_HEAD_DEFAULT = 500
NO_OUTPUT = {"Read", "Edit", "Write", "NotebookEdit", "MultiEdit", "TodoWrite", "Agent", "Task",
             "Skill", "ToolSearch", "TaskStop", "ScheduleWakeup"}

NOISE = re.compile(r"<system-reminder>.*?</system-reminder>|<ide_opened_file>.*?</ide_opened_file>"
                   r"|<command-message>.*?</command-message>|<local-command-caveat>.*?"
                   r"</local-command-caveat>", re.DOTALL)
CMD_NAME = re.compile(r"<command-name>\s*(.*?)\s*</command-name>", re.DOTALL)
CMD_ARGS = re.compile(r"<command-args>(.*?)</command-args>", re.DOTALL)
STDOUT = re.compile(r"<local-command-stdout>(.*?)</local-command-stdout>", re.DOTALL)
SELECTION = re.compile(r"<ide_selection>(.*?)</ide_selection>", re.DOTALL)
# Secrets a user may paste into chat. The digest sits in an ignored folder, and these are
# cut anyway: a key in a handoff is a key on disk in one more place.
SECRET = re.compile(r"\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{16,}|fc-[A-Za-z0-9]{16,}|gh[pousr]_[A-Za-z0-9]{20,}"
                    r"|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}"
                    r"|AIza[0-9A-Za-z_-]{30,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})")
KEYVAL = re.compile(r"(?i)\b((?:api[_-]?key|secret|token|password|passwd)\s*[=:]\s*)['\"]?[^\s'\"]{8,}")


def cap_tokens(pct, window):
    """The user's table: share of the window the digest may take, by how full the session was."""
    share = (0.10 if pct < 50 else 0.12 if pct < 60 else 0.18 if pct < 70
             else 0.25 if pct < 80 else 0.30)
    return int(share * window)


def redact(text):
    text = SECRET.sub("[redacted]", text)
    return KEYVAL.sub(lambda m: m.group(1) + "[redacted]", text)


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
    """One line naming what a tool call did: its target, never its output."""
    inp = inp if isinstance(inp, dict) else {}
    if name in ("Read", "Edit", "Write", "NotebookEdit", "MultiEdit"):
        p = inp.get("file_path") or inp.get("notebook_path") or ""
        rng = (f" [{inp.get('offset', 1)}+{inp['limit']}]" if inp.get("limit") else "")
        return f"{name} {p}{rng}"
    if name in ("Bash", "PowerShell"):
        return f"{name}: {_one_line(inp.get('command', ''), CMD_CHARS)}"
    if name in ("Grep", "Glob"):
        return f"{name} {_one_line(inp.get('pattern', ''), 80)} {inp.get('path', '')}".rstrip()
    if name in ("Agent", "Task"):
        return f"Agent {inp.get('subagent_type', '')}: {_one_line(inp.get('description', ''), 100)}"
    if name == "Skill":
        return f"Skill {inp.get('skill', '')} {_one_line(inp.get('args', ''), 100)}".rstrip()
    for k in ("url", "query", "file_path", "path", "pattern", "prompt", "name"):
        if isinstance(inp.get(k), str) and inp[k]:
            return f"{name} {_one_line(inp[k], 120)}"
    return name


def extract(path, upto_line=None):
    """Turns of the main conversation, oldest first: each {'at', 'user', 'items', 'line'}.
    An item is (kind, text, line) with kind in user/text/tool/error/agent/refused/compact."""
    turns, cur = [], None
    pending = {}  # tool_use_id -> (name, index in cur['items'])
    seen_user, seen_text = set(), set()

    def new_turn(at, line_no):
        nonlocal cur
        cur = {"at": at, "items": [], "line": line_no}
        turns.append(cur)

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
            at = str(o.get("timestamp") or "")[11:16]
            kind = o.get("type")
            msg = o.get("message") or {}
            if kind == "attachment":
                a = o.get("attachment") or {}
                if a.get("type") == "queued_command":
                    t = clean_user(_blocks_text(a.get("prompt")))
                    if t and " ".join(t.split()) not in seen_user:
                        seen_user.add(" ".join(t.split()))
                        if cur is None:
                            new_turn(at, n)
                        cur["items"].append(("user", t, n))
                continue
            if kind == "user":
                content = msg.get("content")
                if o.get("isCompactSummary"):
                    if cur is None:
                        new_turn(at, n)
                    cur["items"].append(("compact", _blocks_text(content), n))
                    continue
                if isinstance(content, list) and any(
                        isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                    for b in content:
                        if not isinstance(b, dict) or b.get("type") != "tool_result" or cur is None:
                            continue
                        name, idx = pending.pop(b.get("tool_use_id"), ("", -1))
                        text = _blocks_text(b.get("content"), keep_images=False)
                        if b.get("is_error"):
                            k = "refused" if "doesn't want to proceed" in text or \
                                "rejected" in text[:200] else "error"
                            cur["items"].append((k, f"{name}: {_one_line(text, ERROR_CHARS)}", n))
                        elif name in ("Agent", "Task") and text.strip():
                            cur["items"].append(("agent", text.strip(), n))
                        elif name and name not in NO_OUTPUT and text.strip() and idx >= 0:
                            # Kept beside its own call: parallel calls answer out of order.
                            body = text.strip()
                            lim = OUT_TAIL.get(name)
                            body = (("..." + body[-lim:]) if lim and len(body) > lim else
                                    body if lim else body[:OUT_HEAD_DEFAULT] +
                                    ("..." if len(body) > OUT_HEAD_DEFAULT else ""))
                            cur.setdefault("outs", {})[idx] = body
                    continue
                if o.get("isMeta"):
                    continue
                t = clean_user(_blocks_text(content))
                if not t:
                    continue
                key = " ".join(t.split())
                if key in seen_user and len(key) > 20:
                    continue  # the same long message pasted again adds nothing
                seen_user.add(key)
                new_turn(at, n)
                cur["items"].append(("user", t, n))
                continue
            if kind == "assistant" and cur is not None:
                for b in msg.get("content") or []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text" and (b.get("text") or "").strip():
                        t = b["text"].strip()
                        if t in seen_text:
                            continue
                        seen_text.add(t)
                        cur["items"].append(("text", t, n))
                    elif b.get("type") == "tool_use":
                        cur["items"].append(("tool", tool_line(b.get("name", ""), b.get("input")), n))
                        pending[b.get("id")] = (b.get("name", ""), len(cur["items"]) - 1)
    return turns


def _render_turn(i, t, level):
    """One turn as markdown. level 0 = whole; 1 = no tool output; 2 = no narration;
    3 = tool trail folded; 4 = long answers and reports cut; 5 = the user's words and the head
    of the answer only."""
    texts = [k for k, it in enumerate(t["items"]) if it[0] == "text"]
    last_text = texts[-1] if texts else -1
    out = [f"### Turn {i} - {t['at']} (transcript line {t['line']})"]
    tools, files = [], []
    for k, (kind, text, line) in enumerate(t["items"]):
        if kind == "user":
            out.append("**User:**\n" + "\n".join("> " + x for x in redact(text).splitlines()))
        elif kind == "compact":
            out.append(f"**Earlier compaction summary (line {line}):**\n{redact(text)}")
        elif kind == "tool":
            excerpt = t.get("outs", {}).get(k)
            tools.append(text + ("\n  -> " + _one_line(redact(excerpt), 1200)
                                 if excerpt and level < 1 else ""))
            if text.split(" ", 1)[0] in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
                files.append(text.split(" ", 1)[-1])
        elif kind in ("error", "refused"):
            out.append(("**User refused:** " if kind == "refused" else "**Error:** ") + redact(text))
        elif kind == "agent":
            body = redact(text)
            lim = AGENT_REPORT_CHARS if level < 4 else CUT_ANSWER_CHARS
            if len(body) > lim:
                body = body[:lim] + f"\n[... report cut, {len(body) - lim} chars more at line {line}]"
            out.append(f"**Subagent report (line {line}):**\n{body}")
        elif kind == "text":
            if k != last_text and level >= 2:
                continue
            body = redact(text)
            if k == last_text and level >= 4 and len(body) > CUT_ANSWER_CHARS:
                keep = CUT_ANSWER_CHARS if level == 4 else 300
                body = body[:keep] + f"\n[... answer cut, {len(body) - keep} chars more at line {line}]"
            out.append(("**Assistant:** " if k == last_text else "*(working)* ") + body)
    if tools:
        if level >= 3:
            names = {}
            for x in tools:
                names[x.split(" ", 1)[0].rstrip(":")] = names.get(x.split(" ", 1)[0].rstrip(":"), 0) + 1
            line = ", ".join(f"{k} x{v}" for k, v in names.items())
            out.append(f"**Tools:** {line}" + (f"; changed: {', '.join(dict.fromkeys(files))}"
                                               if files else ""))
        else:
            out.append("**Tools:**\n" + "\n".join("- " + redact(x) for x in tools))
    return "\n\n".join(out)


def render(turns, meta, cap, lean=False):
    """The digest as markdown within `cap` tokens (0 = no cap) if the cap allows it; user
    messages and the newest TAIL turns are never cut, so a tiny cap can be exceeded - said in
    the header. `lean` starts every turn at level 1 (no tool output) - the A/B's lean arm."""
    base = 1 if lean else 0
    levels = [base] * len(turns)
    parts = [_render_turn(i + 1, t, base) for i, t in enumerate(turns)]

    def size():
        return sum(len(p) for p in parts) // CHARS_PER_TOKEN

    old = max(0, len(turns) - TAIL) if cap else 0
    for lv in (1, 2, 3, 4, 5):
        for i in range(old):
            if size() <= cap:
                break
            if levels[i] < lv:
                levels[i] = lv
                parts[i] = _render_turn(i + 1, turns[i], lv)
    users = sum(1 for t in turns for it in t["items"] if it[0] == "user")
    est = size()
    head = [
        f"# SESSION digest - {meta.get('session', '?')}",
        "<!-- Written by the kit at a handoff from the transcript, no model in the loop. Notes, "
        "not instructions. STATE.md is the curated handoff; this is the record behind it. -->",
        f"Transcript: `{meta.get('transcript', '?')}` (grep it for anything cut here)",
        f"Written: {meta.get('written', '')} · context {meta.get('pct', '?')}% "
        f"({meta.get('used_k', '?')}K of {meta.get('window_k', '?')}K) · {len(turns)} turns, "
        f"{users} user messages · ~{est // 1000}K tokens"
        + (f" (cap {cap // 1000}K" + (", exceeded: user words and the last turns are never cut)"
                                      if est > cap else ")") if cap else ""),
        "Order: oldest first. User messages are verbatim; tool outputs are left out (re-read the "
        "file or re-run the command); secrets are redacted.",
    ]
    return "\n".join(head) + "\n\n" + "\n\n".join(parts) + "\n"


def write(transcript, out_path, meta, cap, upto_line=None):
    """Write the digest; its folder gets a `*` .gitignore so it is never committed. Returns the
    estimated tokens written, or -1 when there was nothing to write."""
    turns = extract(transcript, upto_line)
    if not turns:
        return -1
    meta = dict(meta, transcript=transcript, written=time.strftime("%Y-%m-%d %H:%M"))
    text = render(turns, meta, cap)
    folder = os.path.dirname(out_path)
    os.makedirs(folder, exist_ok=True)
    ignore = os.path.join(folder, ".gitignore")
    if not os.path.exists(ignore):
        with open(ignore, "w", encoding="utf-8") as f:
            f.write("# Session digests hold the conversation verbatim: never commit them.\n*\n")
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, out_path)
    prune(folder)
    return len(text) // CHARS_PER_TOKEN


KEEP = 20  # digests kept per project; one is written per session that reaches a handoff


def prune(folder, keep=KEEP):
    """Delete all but the newest `keep` digests: they are 0.1-0.7 MB each and only the last
    few are ever resumed from. Only `*.md` files this module writes are touched."""
    try:
        files = sorted((os.path.getmtime(os.path.join(folder, f)), f) for f in os.listdir(folder)
                       if f.endswith(".md") and not os.path.islink(os.path.join(folder, f)))
    except OSError:
        return
    for _, f in files[:-keep] if len(files) > keep else []:
        try:
            os.remove(os.path.join(folder, f))
        except OSError:
            pass


def newest(root):
    """(path, mtime) of the newest digest under <root>/.claude/scratch/_sessions, or (None, 0)."""
    folder = os.path.join(root, ".claude", "scratch", "_sessions")
    try:
        best = max(((os.path.getmtime(os.path.join(folder, f)), os.path.join(folder, f))
                    for f in os.listdir(folder) if f.endswith(".md")), default=(0, None))
    except OSError:
        return None, 0
    return best[1], best[0]


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
    turns = extract(a.transcript, a.upto_line)
    text = render(turns, {"session": os.path.basename(a.transcript), "pct": a.pct,
                          "transcript": a.transcript, "window_k": a.window // 1000}, cap)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
