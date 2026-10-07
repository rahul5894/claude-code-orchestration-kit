"""Replay every shell md-guard denial through the CURRENT md-guard and say why it denies.

Usage: python classify_shell.py [--since YYYY-MM-DD]
"""
import argparse, glob, importlib.util, json, os, re, sys
from collections import Counter
HOOK = os.path.join(os.path.dirname(__file__), "..", "..", "core", "hooks", "md-guard.py")
spec = importlib.util.spec_from_file_location("mdguard", HOOK)
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
ap = argparse.ArgumentParser(); ap.add_argument("--since", default=""); a = ap.parse_args()
why, ex, mrw = Counter(), {}, Counter()
files = glob.glob(os.path.expanduser("~/.claude/projects/**/*.jsonl"), recursive=True)
for path in files:
    uses = {}
    cwd = ""
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if '"tool_use"' not in line and '"tool_result"' not in line:
                continue
            try: o = json.loads(line)
            except ValueError: continue
            cwd = o.get("cwd") or cwd
            ts = str(o.get("timestamp") or "")
            if a.since and ts[:10] < a.since: continue
            for b in (o.get("message") or {}).get("content") or []:
                if not isinstance(b, dict): continue
                if b.get("type") == "tool_use":
                    uses[b.get("id")] = (b.get("name"), b.get("input") or {}, cwd)
                elif b.get("type") == "tool_result":
                    u = uses.get(b.get("tool_use_id"))
                    c = b.get("content"); t = c if isinstance(c, str) else "".join(x.get("text", "") for x in c or [] if isinstance(x, dict))
                    if not u or "md-guard:" not in t or "read-only agent" in t or u[0] == "Read": continue
                    cmd, base = u[1].get("command", ""), u[2] if os.path.isdir(u[2] or "") else os.getcwd()
                    stripped = g._strip_heredocs(cmd)
                    if not g._reads_big_md(stripped, base, u[0]):
                        k = "now-allowed (guard since fixed or file shrank)"
                    elif g.MD_OPTION.search(cmd):
                        k = "recursive .md filter (--include=*.md / -g)"
                    else:
                        toks = g._md_tokens(stripped); res = [g._resolve(p, base) for p in toks]
                        if any(r is None for r in res):
                            bad = [p for p, r in zip(toks, res) if r is None]
                            k = "unresolved path: $VAR" if any("$" in p for p in bad) else ("unresolved path: glob" if any(ch in "".join(bad) for ch in "*?[") else "unresolved path: missing/relative")
                        else:
                            n = max(g.line_count(x) for r in res for x in r)
                            k = "big file (>300 lines)" if n > 300 else "small file?"
                    why[k] += 1; ex.setdefault(k, cmd[:160].replace("\n", " "))
                    if re.search(r"(?:CLAUDE|AGENTS|STATE|DECISIONS|FINDINGS|SKILL|INDEX)\.md", cmd):
                        mrw[k] += 1
tot = sum(why.values())
print(f"shell denials replayed: {tot} (since {a.since or 'all time'})")
for k, v in why.most_common(): print(f"  {v:5d} {v*100//max(tot,1):3d}%  {k}\n          e.g. {ex[k]}")

print("must-read-named commands by class:")
for k, v in mrw.most_common():
    print(f"  {v:5d}  {k}")
