"""Real handoff chains: session A got kit-context's Stop block, session B in the same project
started with /continue after A ended. Prints candidates; --json writes them.
Usage: python chains.py [--since 2026-09-29] [--json chains.json]"""
import argparse, glob, json, os, re
ap = argparse.ArgumentParser(); ap.add_argument("--since", default="2026-09-29"); ap.add_argument("--json"); a = ap.parse_args()
def info(p):
    first_ts = last_ts = first_user = ""; block = 0; n = 0
    with open(p, encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, 1):
            m = re.search(r'"timestamp":"([^"]+)"', line)
            if m:
                first_ts = first_ts or m.group(1); last_ts = m.group(1)
            if not block and '"hook_blocking_error"' in line and "context is at" in line: block = n
            if not first_user and '"type":"user"' in line and '"tool_result"' not in line and '"isMeta":true' not in line:
                try:
                    o = json.loads(line); c = (o.get("message") or {}).get("content")
                    t = c if isinstance(c, str) else " ".join(b.get("text", "") for b in c or [] if isinstance(b, dict))
                    t = re.sub(r"<system-reminder>.*?</system-reminder>|<ide_[a-z_]+>.*?</ide_[a-z_]+>", "", t, flags=re.S).strip()
                    if t: first_user = t[:120]
                except ValueError: pass
    return {"path": p, "first": first_ts, "last": last_ts, "block": block, "lines": n, "first_user": first_user}
out = []
for d in glob.glob(os.path.expanduser("~/.claude/projects/*")):
    ss = [info(p) for p in glob.glob(os.path.join(d, "*.jsonl")) if os.path.getsize(p) > 20000]
    ss = [s for s in ss if s["first"]]
    ss.sort(key=lambda s: s["first"])
    for i, s in enumerate(ss):
        if not s["block"] or s["first"][:10] < a.since: continue
        from datetime import datetime, timedelta
        def ts(x): return datetime.fromisoformat(x.replace("Z", "+00:00")[:19])
        nxt = [t for t in ss[i+1:] if ts(s["last"]) - timedelta(minutes=5) <= ts(t["first"]) <= ts(s["last"]) + timedelta(hours=2)]
        if nxt:
            b = nxt[0]
            out.append({"project": os.path.basename(d), "A": s["path"], "A_lines": s["lines"], "A_block": s["block"], "A_last": s["last"], "B": b["path"], "B_first": b["first"], "B_first_user": b["first_user"]})
for c in out:
    print(f"{c['project'][:30]:30} A={os.path.basename(c['A'])[:8]} ({os.path.getsize(c['A'])//1000000}MB, end {c['A_last'][:16]}) -> B={os.path.basename(c['B'])[:8]} start {c['B_first'][:16]} | {c['B_first_user'][:50]!r}")
if a.json: json.dump(out, open(a.json, "w", encoding="utf-8"), indent=1)
print(len(out), "chains")
