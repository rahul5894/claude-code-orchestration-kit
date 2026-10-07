"""Build the A/B materials for one real handoff chain (session A handed off, B resumed).

Writes bench/results/handoff-ab/<name>/ (gitignored - it holds other projects' conversations):
  kit_now.md     what B was actually given at /continue: the SessionStart context plus every
                 tool result of B's reads of STATE/DECISIONS/FINDINGS/INDEX before B's first edit
  digest_full.md kit_digest of A at A's end (with output excerpts)
  digest_lean.md the same without tool output
  kit_new.md     kit_now.md + digest_full.md (the proposed handoff)
  raw_A.md       A as text for the probe writer: user, assistant, tool calls WITH outputs
  b_excerpt.md   B's first turns (what the next session went on to need)

Usage: python prep.py <name> <A.jsonl> <B.jsonl>
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "core", "hooks"))
import kit_digest as kd  # noqa: E402

OUT = os.path.join(HERE, "..", "results", "handoff-ab")
HANDOFF_FILE = re.compile(r"(?:STATE|DECISIONS|FINDINGS|INDEX)\.md|[/\\]handoffs[/\\]", re.IGNORECASE)
WRITE_SHAPE = re.compile(r">>|cat\s*>|\btee\b|sed -i|write_text|\.write\(|\.replace\(|Set-Content"
                         r"|Out-File|open\([^)]*['\"]w")


def rows_of(path):
    """(line number, object) per parseable JSON line; a torn or blank line is skipped."""
    for n, line in enumerate(open(path, encoding="utf-8", errors="replace"), 1):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if isinstance(o, dict):
            yield n, o


def text_of(c):
    if isinstance(c, str):
        return c
    return "\n".join(b.get("text", "") for b in c or [] if isinstance(b, dict) and b.get("type") == "text")


def kit_now(b_path):
    """What /continue handed B: the SessionStart context, then the results of B's opening
    reads - the bucket files and git's state - up to B's first write or 8th call, whichever
    comes first. Nothing B did after that leaks in."""
    parts, uses, calls, stop = [], {}, 0, False
    for _, o in rows_of(b_path):
        if o.get("isSidechain"):
            continue
        a = o.get("attachment") or {}
        if a.get("type") == "hook_additional_context" and not parts:
            c = a.get("content")
            parts.append("## SessionStart context\n" + ("\n".join(c) if isinstance(c, list) else str(c)))
        m = o.get("message") or {}
        if o.get("type") == "assistant" and not stop:
            for b in m.get("content") or []:
                if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                    continue
                calls += 1
                s = json.dumps(b.get("input"))
                if b["name"] in ("Edit", "Write") or WRITE_SHAPE.search(s) or calls > 8:
                    stop = True
                    break
                if HANDOFF_FILE.search(s) or re.search(r"git (?:rev-parse|status|log)", s):
                    uses[b["id"]] = f"{b['name']} {s[:200]}"
        elif o.get("type") == "user" and isinstance(m.get("content"), list):
            for b in m["content"]:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("tool_use_id") in uses:
                    parts.append(f"## {uses.pop(b['tool_use_id'])}\n{text_of(b.get('content'))}")
        if stop and not uses:
            break
    return "\n\n".join(parts)


def raw_dump(a_path, out_cap):
    """A as plain text with tool outputs, each output cut to `out_cap` chars."""
    rows, names = [], {}
    for n, o in rows_of(a_path):
        if o.get("isSidechain") or o.get("isMeta"):
            continue
        m = o.get("message") or {}
        t = o.get("type")
        if t == "user":
            c = m.get("content")
            if isinstance(c, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        r = text_of(b.get("content"))
                        if len(r) > out_cap:
                            r = r[:out_cap // 2] + f"\n[...{len(r) - out_cap} chars...]\n" + r[-out_cap // 2:]
                        rows.append(f"[L{n} RESULT{' ERROR' if b.get('is_error') else ''} "
                                    f"{names.get(b.get('tool_use_id'), '')}]\n{r}")
            else:
                u = kd.clean_user(text_of(c))
                if u:
                    rows.append(f"[L{n} USER {str(o.get('timestamp'))[:16]}]\n{u}")
        elif t == "assistant":
            for b in m.get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text", "").strip():
                    rows.append(f"[L{n} ASSISTANT]\n{b['text']}")
                elif b.get("type") == "tool_use":
                    names[b["id"]] = b["name"]
                    rows.append(f"[L{n} TOOL {b['name']}] {json.dumps(b.get('input'))[:1500]}")
        elif t == "attachment" and (o.get("attachment") or {}).get("type") == "queued_command":
            rows.append(f"[L{n} USER (queued)]\n{kd.clean_user(text_of((o['attachment']).get('prompt')))}")
    return "\n\n".join(rows)


def b_excerpt(b_path, limit=60):
    rows = []
    for n, o in rows_of(b_path):
        m = o.get("message") or {}
        if o.get("isSidechain") or o.get("isMeta"):
            continue
        if o.get("type") == "user" and not (isinstance(m.get("content"), list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in m["content"])):
            u = kd.clean_user(text_of(m.get("content")))
            if u:
                rows.append(f"[B USER] {u}")
        elif o.get("type") == "assistant":
            for b in m.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip():
                    rows.append(f"[B ASSISTANT] {b['text'][:1500]}")
                elif isinstance(b, dict) and b.get("type") == "tool_use":
                    rows.append(f"[B TOOL] {kd.tool_line(b['name'], b.get('input'))}")
        if len(rows) >= limit:
            break
    return "\n".join(rows)


def main(name, a_path, b_path):
    d = os.path.join(OUT, name)
    os.makedirs(d, exist_ok=True)
    turns = kd.extract(a_path)
    meta = {"session": os.path.basename(a_path)[:36], "transcript": a_path}
    files = {
        "kit_now.md": kit_now(b_path),
        "digest_full.md": kd.render(turns, meta, 0),
        "digest_lean.md": kd.render(turns, meta, 0, lean=True),
        "b_excerpt.md": b_excerpt(b_path),
    }
    files["kit_new.md"] = files["kit_now.md"] + "\n\n---\n\n" + files["digest_full.md"]
    raw = raw_dump(a_path, 2000)
    if len(raw) > 2_400_000:
        raw = raw_dump(a_path, 500)
    files["raw_A.md"] = raw
    for fn, text in files.items():
        with open(os.path.join(d, fn), "w", encoding="utf-8") as f:
            f.write(text)
        print(f"{name}/{fn}: ~{len(text) // 4 // 1000}K tokens")


if __name__ == "__main__":
    main(*sys.argv[1:4])
