"""md-guard A/B, live: does an agent end up with the WHOLE answer, and at what cost?

Three guards (none / old = d5da6a2 / new = working tree) x three tasks x N runs, each a
headless `claude -p` on the bundled binary with ONLY that guard registered (--setting-sources
project, so the installed user hooks stay out). Scores: correct, turns, input tokens, cost.

  S1 lookup  - a 700-line doc, one fact on line 641 that no heading points at
  S2 spec    - a 900-line SPEC.md with 12 requirements spread through it; all 12 are needed
  S3 brief   - a 600-line brief under briefs/ whose binding instruction sits on line 580

Usage: python guard_probe.py [--runs 2]   (writes bench/results/guard-probe/results.json)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
EXE = os.environ.get("CLAUDE_CODE_EXECPATH") or "claude"
OUT = os.path.join(REPO, "bench", "results", "guard-probe")
# The guard before the 2026-10-07 rewrite, pinned: HEAD is the new guard since 54b27b3.
OLD_REV = "d5da6a2"


def fixtures(d):
    with open(os.path.join(d, "guide.md"), "w", encoding="utf-8") as f:
        f.write("".join((f"## Part {i // 50}\n" if i % 50 == 0 else
                         f"text {i}: " + ("the vault code is PURPLE-42" if i == 640 else "routine filler line about nothing") + "\n")
                        for i in range(700)))
    reqs, lines = [], []
    for i in range(900):
        if i % 75 == 0:
            lines.append(f"## Section {i // 75}\n")
        elif i % 75 == 37:
            k = i // 75 + 1
            reqs.append(f"REQ-{k:02d}")
            lines.append(f"REQ-{k:02d}: the system must log event type {k * 7}\n")
        else:
            lines.append(f"Background prose {i}, explaining context that is not a requirement.\n")
    with open(os.path.join(d, "SPEC.md"), "w", encoding="utf-8") as f:
        f.write("".join(lines))
    b = os.path.join(d, ".claude", "scratch", "t1", "briefs")
    os.makedirs(b)
    with open(os.path.join(b, "01-task.md"), "w", encoding="utf-8") as f:
        f.write("".join(("# Brief 01\n" if i == 0 else
                         "Use port 8443 for the service, never 8080. Deliverable: svc-bundle.zip\n" if i == 579 else
                         f"Context line {i}: background the builder may skim.\n") for i in range(600)))
    return reqs


TASKS = {
    "S1": ("What is the vault code written in guide.md? Answer with the code only.",
           lambda r, reqs: "PURPLE-42" in r),
    "S2": ("Read SPEC.md and list EVERY requirement ID (REQ-xx) it contains, then the count. "
           "Answer as: IDS: <comma list> COUNT: <n>.",
           lambda r, reqs: all(x in r for x in reqs) and re.search(r"COUNT:\s*12\b", r) is not None),
    "S3": ("You are the builder. Read your brief .claude/scratch/t1/briefs/01-task.md and tell me "
           "which port the service must use and the deliverable's file name. Answer: PORT=<n> FILE=<name>.",
           lambda r, reqs: "8443" in r and "svc-bundle.zip" in r and "PORT=8080" not in r),
}


def guard_file(variant, d):
    if variant == "none":
        return None
    g = os.path.join(d, "_guard")
    os.makedirs(g, exist_ok=True)
    shutil.copy(os.path.join(REPO, "core", "hooks", "kit_off.py"), g)
    if variant == "new":
        shutil.copy(os.path.join(REPO, "core", "hooks", "md-guard.py"), g)
    else:
        src = subprocess.run(["git", "-C", REPO, "show", OLD_REV + ":core/hooks/md-guard.py"],
                             capture_output=True).stdout
        with open(os.path.join(g, "md-guard.py"), "wb") as f:
            f.write(src)
    return os.path.join(g, "md-guard.py").replace("\\", "/")


def run(variant, task, k):
    d = tempfile.mkdtemp(prefix=f"gp-{variant}-{task}-")
    reqs = fixtures(d)
    g = guard_file(variant, d)
    hooks = ({"PreToolUse": [{"matcher": "Read|Bash|PowerShell", "hooks": [
        {"type": "command", "command": f"python {g}", "timeout": 5}]}]} if g else {})
    with open(os.path.join(d, "settings.json"), "w") as f:
        json.dump({"hooks": hooks}, f)
    prompt, ok = TASKS[task]
    r = subprocess.run([EXE, "-p", "--setting-sources", "project", "--settings", "settings.json",
                        "--no-session-persistence", "--model", "claude-opus-5-5",
                        "--output-format", "json", "--tools", "Read,Bash"],
                       input=prompt.encode(), capture_output=True, cwd=d, timeout=900,
                       env=dict(os.environ, MSYS_NO_PATHCONV="1"))
    shutil.rmtree(d, ignore_errors=True)
    try:
        o = json.loads(r.stdout.decode("utf-8"))
    except ValueError:
        return {"variant": variant, "task": task, "k": k, "error": r.stderr.decode()[-300:]}
    u = o.get("usage") or {}
    res = o.get("result") or ""
    return {"variant": variant, "task": task, "k": k, "correct": bool(ok(res, reqs)),
            "turns": o.get("num_turns"), "cost": o.get("total_cost_usd"),
            "in": sum(int(u.get(x) or 0) for x in ("input_tokens", "cache_creation_input_tokens",
                                                   "cache_read_input_tokens")),
            "answer": res[-300:]}


def main():
    runs = int(sys.argv[sys.argv.index("--runs") + 1]) if "--runs" in sys.argv else 2
    import concurrent.futures as cf
    jobs = [(v, t, k) for k in range(runs) for t in TASKS for v in ("none", "old", "new")]
    os.makedirs(OUT, exist_ok=True)
    with cf.ThreadPoolExecutor(6) as ex:
        results = list(ex.map(lambda j: run(*j), jobs))
    with open(os.path.join(OUT, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
    print(f"{'task':4} {'guard':5} {'correct':>8} {'turns':>6} {'in tok':>8} {'cost $':>7}")
    for t in TASKS:
        for v in ("none", "old", "new"):
            rs = [x for x in results if x["task"] == t and x["variant"] == v and "error" not in x]
            if not rs:
                print(f"{t:4} {v:5} errors")
                continue
            print(f"{t:4} {v:5} {sum(x['correct'] for x in rs):>4}/{len(rs):<3} "
                  f"{sum(x['turns'] or 0 for x in rs) / len(rs):>6.1f} {sum(x['in'] for x in rs) // len(rs):>8} "
                  f"{sum(x['cost'] or 0 for x in rs) / len(rs):>7.3f}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
