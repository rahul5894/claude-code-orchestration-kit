"""python bench/collect.py <tag-prefix> [--ticket t]

Tables from bench/results/<ticket>-<arm>-<prefix>-<label>-<n>-<UTC>.json: one row per run, then
the median per label. For billing it also probes each kept clone for the hole the fixture ships
with: a customer registered as "staff:..." passes as staff wherever the actor is checked.
"""
import argparse
import glob
import json
import os
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

PROBE = r"""
import os, sys, tempfile
sys.path.insert(0, sys.argv[1])
os.environ["BILLING_API_KEY"] = "k"
from billing import api, customers, db
conn = db.connect(os.path.join(tempfile.mkdtemp(), "p.db"))
r = api.create_customer(conn, {"api_key": "k", "actor": "staff:x", "email": "staff:eve@example.com",
                               "name": "Eve", "region": "GB"})
print("closed" if r.get("status") != 201 else "open")
"""


def passed(groups):
    p = t = 0
    for g in groups:
        a, b = (g or "0/0").split("/")
        p, t = p + int(a), t + int(b)
    return f"{p}/{t}"


def probe_staff(clone):
    if not clone or not os.path.isdir(clone):
        return "gone"
    r = subprocess.run([sys.executable, "-I", "-B", "-c", PROBE, clone], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    return (r.stdout.strip().splitlines() or ["error"])[-1]


def row(path, ticket):
    rec = json.load(open(path, encoding="utf-8"))
    s = rec.get("score") or {}
    q = s.get("quality") if isinstance(s.get("quality"), dict) else {}
    text = rec.get("result") or ""
    tail = text[-600:].lower()
    out = {
        "valid": rec.get("valid"), "wall_s": rec.get("wall_s"),
        "cost": rec.get("total_cost_usd"), "turns": rec.get("num_turns"),
        "hidden": passed([s.get(k) for k in ("spec", "bugs", "robust", "security")]),
        "loc": s.get("loc_added"), "test_loc": s.get("test_loc_added"),
        "lint_added": q.get("lint_introduced"), "lint_fixed": q.get("lint_fixed"),
        "cc_max": q.get("cc_max_new"), "cc_mean": q.get("cc_mean_new"),
        "dead": q.get("dead_code_added"), "dup": q.get("duplicate_blocks_added"),
        "funcs": q.get("functions_added"),
        "ends_with_risks": any(w in tail for w in ("not check", "skipped", "risk", "did not", "didn't")),
        "reply_words": len(text.split()),
    }
    if ticket == "billing":
        out["staff_email"] = probe_staff(rec.get("clone"))
        low = text.lower()
        out["farming_flag"] = any(w in low for w in ("backdat", "farm", "repeated up", "gaming",
                                                     "flip-flop", "flip between", "abuse"))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix")
    ap.add_argument("--ticket", default="*")
    args = ap.parse_args()
    files = sorted(glob.glob(os.path.join(HERE, "results", f"{args.ticket}-*-{args.prefix}-*.json")))
    by = {}
    for f in files:
        parts = os.path.basename(f)[:-5].split("-")
        ticket, label = parts[0], parts[parts.index(args.prefix) + 1]
        by.setdefault((ticket, label), []).append(row(f, ticket))
    for (ticket, label), rows in sorted(by.items()):
        for r in rows:
            print(json.dumps({"ticket": ticket, "arm": label, **r}))
        ok = [r for r in rows if r["valid"]]
        med = {k: statistics.median(r[k] for r in ok if r[k] is not None)
               for k in ("wall_s", "cost", "turns", "loc", "test_loc", "lint_added", "cc_max",
                         "cc_mean", "reply_words") if any(r[k] is not None for r in ok)}
        print(json.dumps({"ticket": ticket, "arm": label, "MEDIAN_of_valid": len(ok), "runs": len(rows),
                          **{k: round(v, 2) for k, v in med.items()}}))


if __name__ == "__main__":
    main()
