"""For every main transcript where kit-context blocked for a handoff: context at the first block,
and the digest's natural size (no cap) and capped size at that line.
Usage: python measure_digest.py [--since YYYY-MM-DD] [--limit N]"""
import argparse, glob, importlib.util, json, os, re, sys
H = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "core", "hooks")
sys.path.insert(0, H)
import kit_digest as kd
spec = importlib.util.spec_from_file_location("kc", os.path.join(H, "kit-context.py")); kc = importlib.util.module_from_spec(spec); spec.loader.exec_module(kc)
ap = argparse.ArgumentParser(); ap.add_argument("--since", default="2026-09-20"); ap.add_argument("--limit", type=int, default=60); a = ap.parse_args()
rows = []
for p in glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")):
    if os.path.getsize(p) < 1_000_000: continue
    first, used, named = None, 0, ""
    with open(p, encoding="utf-8", errors="replace") as f:
        for n, line in enumerate(f, 1):
            if '"usage"' in line or '"modelId"' in line:
                try: o = json.loads(line)
                except ValueError: o = {}
                if o.get("type") == "assistant" and o.get("isSidechain") is False:
                    u = (o.get("message") or {}).get("usage") or {}
                    s = sum(int(u.get(k) or 0) for k in ("input_tokens","cache_creation_input_tokens","cache_read_input_tokens"))
                    used = s or used
                elif o.get("type") == "attachment" and (o.get("attachment") or {}).get("type") == "model":
                    named = str(((o.get("attachment") or {}).get("identity") or {}).get("modelId") or named)
            if '"hook_blocking_error"' in line and "context is at" in line:
                ts = re.search(r'"timestamp":"([0-9-]{10})', line)
                if ts and ts.group(1) >= a.since: first = n
                break
    if not first: continue
    w = kc.window(named) if named else 1_000_000
    pct = used * 100 // w
    turns = kd.extract(p, first)
    nat = len(kd.render(turns, {}, 0)) // 4
    lean = len(kd.render([dict(t, outs={}) for t in turns], {}, 0)) // 4
    cap = kd.cap_tokens(pct, w)
    capped = len(kd.render(turns, {}, cap)) // 4
    users = sum(1 for t in turns for it in t["items"] if it[0] == "user")
    rows.append((os.path.basename(os.path.dirname(p))[:28], os.path.basename(p)[:8], pct, used // 1000, w // 1000, len(turns), users, nat // 1000, cap // 1000, capped // 1000, lean // 1000))
rows.sort(key=lambda r: r[2])
print(f"{'project':28} {'sess':8} {'pct':>4} {'usedK':>6} {'winK':>5} {'turns':>5} {'umsg':>4} {'natK':>5} {'capK':>5} {'outK':>5} {'leanK':>5}  full/used lean/used")
for r in rows[:a.limit]:
    print(f"{r[0]:28} {r[1]:8} {r[2]:>4} {r[3]:>6} {r[4]:>5} {r[5]:>5} {r[6]:>4} {r[7]:>5} {r[8]:>5} {r[9]:>5} {r[10]:>5}  {r[7]*100//max(r[3],1):>3}% {r[10]*100//max(r[3],1):>3}%")
