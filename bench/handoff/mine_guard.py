"""Mine every Claude Code transcript for md-guard denials and what the agent did next.

For each denial of a big-.md read: which file, how far into the session it came, and how much
of the file the same transcript then read with Read windows (union of line ranges / lines now).

Usage: python mine_guard.py [--since YYYY-MM-DD] [--json out.json]
Reads ~/.claude/projects/**/*.jsonl only. Writes nothing unless --json is given.
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import Counter

ROOT = os.path.expanduser("~/.claude/projects")
MUST_READ = re.compile(r"(?:^|[/\\])(?:CLAUDE|AGENTS|STATE|DECISIONS|FINDINGS|SKILL|INDEX|SESSION)\.md$"
                       r"|[/\\](?:briefs|reports|handoffs|memory|scratch)[/\\]", re.IGNORECASE)
MD_TOKEN = re.compile(r"[^\s\"'|<>;&()`]+\.md\b", re.IGNORECASE)


def norm(p):
    p = (p or "").strip("'\"").replace("\\", "/")
    if re.match(r"^/[a-zA-Z]/", p):
        p = p[1].upper() + ":" + p[2:]
    return p.lower()


def line_count(path):
    try:
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def scan(path, since):
    uses, events = {}, []
    order = 0
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return []
    with f:
        for line in f:
            if '"tool_use"' not in line and '"tool_result"' not in line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            ts = str(obj.get("timestamp") or "")
            if since and ts and ts[:10] < since:
                continue
            msg = obj.get("message") or {}
            for b in msg.get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    order += 1
                    uses[b.get("id")] = (order, b.get("name"), b.get("input") or {}, ts)
                elif b.get("type") == "tool_result":
                    u = uses.get(b.get("tool_use_id"))
                    if not u:
                        continue
                    t = text_of(b.get("content"))
                    events.append((u, t, bool(b.get("is_error"))))
    return events


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    files = glob.glob(os.path.join(ROOT, "**", "*.jsonl"), recursive=True)
    rows = []
    for path in files:
        ev = scan(path, a.since)
        if not ev:
            continue
        sub = "/subagents/" in path.replace("\\", "/")
        for i, ((order, tool, inp, ts), text, err) in enumerate(ev):
            if "md-guard:" not in text or "read-only agent" in text:
                continue
            if tool == "Read":
                targets = [inp.get("file_path", "")]
            else:
                targets = MD_TOKEN.findall(str(inp.get("command", "")))
            kind = "Read" if tool == "Read" else "shell"
            for t in targets or ["?"]:
                n = norm(t)
                total = line_count(t) if os.path.isabs(t.strip("'\"")) or re.match(r"^[a-zA-Z]:", t) else 0
                # what the same transcript read of that file afterwards
                covered, reads, whole_after = set(), 0, False
                for (o2, tool2, inp2, _), text2, err2 in ev[i + 1:]:
                    if tool2 != "Read" or norm(inp2.get("file_path", "")) != n or err2:
                        continue
                    reads += 1
                    off = int(inp2.get("offset") or 1)
                    lim = inp2.get("limit")
                    if lim is None:
                        whole_after = True
                        if total:
                            covered.update(range(1, total + 1))
                        continue
                    covered.update(range(max(off, 1), off + int(lim)))
                cov = (len([x for x in covered if x <= total]) / total) if total else None
                rows.append({
                    "file": t, "kind": kind, "lines_now": total, "order": order, "sub": sub,
                    "must_read": bool(MUST_READ.search(t.replace("\\", "/"))),
                    "reads_after": reads, "coverage": cov, "date": ts[:10],
                    "small": 0 < total <= 300,
                })
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(rows, f, indent=1)
    n = len(rows)
    print(f"denials: {n} (since {a.since or 'all time'}) in {len(files)} transcripts")
    if not n:
        return
    c = Counter(r["kind"] for r in rows)
    print("by kind:", dict(c))
    print("in a subagent:", sum(r["sub"] for r in rows))
    print("early (within first 15 tool calls of its transcript):", sum(r["order"] <= 15 for r in rows))
    print("must-read docs (CLAUDE/STATE/DECISIONS/FINDINGS/briefs/handoffs/SKILL...):",
          sum(r["must_read"] for r in rows))
    print("file now <=300 lines (false denial or file shrank):", sum(r["small"] for r in rows))
    known = [r for r in rows if r["coverage"] is not None and r["lines_now"] > 300]
    buckets = Counter()
    for r in known:
        cv = r["coverage"]
        buckets["none (0%)" if cv == 0 else "full (>=95%)" if cv >= 0.95 else
                "partial <50%" if cv < 0.5 else "partial 50-95%"] += 1
    print(f"big file still on disk: {len(known)}; coverage read afterwards:", dict(buckets))
    mr = [r for r in known if r["must_read"]]
    print(f"  of which must-read: {len(mr)};",
          dict(Counter("full" if r["coverage"] >= 0.95 else "partial/none" for r in mr)))
    print("top files:")
    for f_, k in Counter(os.path.basename(r["file"]) for r in rows).most_common(15):
        print(f"  {k:4d}  {f_}")


if __name__ == "__main__":
    sys.exit(main())
