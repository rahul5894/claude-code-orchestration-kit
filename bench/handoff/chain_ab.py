"""Step-back A/B (bucket handoff-timeline): when a resumed session needs a fact from an EARLIER
session of a long task, does it find it - and how much does that cost - with the old kit or
with the timeline?

Real chains (one task over 5-10 sessions, transcripts still on disk). The resume point is NOW:
the bucket's current STATE.md, DECISIONS.md and FINDINGS.md, as the user would /continue it.
Each arm gets a sandbox copy of the project's scratch: the task's bucket and one other task's
bucket (a distractor: never the place to look).
  old  the old kit at its BEST: the 5 newest session digests (KEEP=5; it really wrote one only
       past 45%), no SESSIONS.md, no STATE snapshots; the old task.md resume rules.
  new  every session's digest + STATE snapshot + SESSIONS.md (kit_chain.finish over the
       transcripts); the new task.md resume rules.
Opus writes 16 probes from the whole record: 10 "earlier" (the answer is only in an earlier
session, not in the current handoff nor the last session's digest) + 6 "any". A reader (Opus,
Read/Grep/Glob only, --safe-mode, cwd = the sandbox) follows its arm's rules, then answers; a
blind grader scores (ab.py). Logged per run: tokens, cost, tool calls, files opened, whether the
distractor bucket was opened.

    python bench/handoff/chain_ab.py prep|probes|read|grade|report [chain ...] [--samples 2]
Results: bench/results/chain-ab/<chain>/ (gitignored).
"""
import concurrent.futures as cf
import json
import os
import random
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "core", "hooks"))
import ab  # noqa: E402
import kit_chain as kc  # noqa: E402
import kit_digest as kd  # noqa: E402

OUT = os.path.join(REPO, "bench", "results", "chain-ab")
EXE = ab.EXE
MODEL = ab.MODEL
CHAINS = {
    "b2s": ("D:/Projects/my-scraper-project", "b2-storage", "gregg-onboarding"),
    "savings": ("D:/Projects/qartez-mcp", "qartez-session-savings", "jev-whole-repo"),
    "ui": ("D:/Projects/Frontdesk", "ui-first-screens", "company-setup"),
    "ector": ("D:/Projects/my-scraper-project", "ector-takeoff-assumed-names", "angelina-onboarding"),
}
OLD_REF = "47538bf"
PROBE_CAP = 30_000  # tokens per earlier-session digest shown to the probe writer

PROBE_PROMPT = """You are building a test of whether an AI that resumes a LONG task after /clear can
recover facts from its EARLIER sessions. Below are the records of one task: the verbatim digests of
sessions S1..S{N1} (oldest first), then the CURRENT handoff (STATE.md, DECISIONS.md, FINDINGS.md as
they are now), then the digest of the LAST session S{N}.

Write exactly 16 probe questions a successor continuing this task could need:
- 10 with kind "earlier": the answer is stated in S1..S{N1} and is NOT stated in the current handoff
  nor in the last session's digest. It must still matter for continuing the task: a user
  instruction, preference or worry (their own words where they matter), a decision and its reason,
  a trap that failed and must not be retried, an exact literal (path, command, ID, number, value),
  or the why behind the work.
- 6 with kind "any": the answer is anywhere in the material and is needed to continue.
Rules: one fact per question; short checkable answers; exact literals; never trivia that only
mattered inside one session; never about another task. Output ONLY JSON:
{"probes":[{"id":"P1","kind":"earlier","category":"user_instruction|decision|literal|trap|why|state_done|next","question":"...","gold":"...","source":"S<k>"}]}

{RECORDS}

=== CURRENT HANDOFF ===
{HANDOFF}

=== LAST SESSION S{N} ===
{LAST}
"""

READER_PROMPT = """You are resuming the task in bucket `.claude/scratch/{SLUG}/` of this project after
/clear. This project's resume rules for a task bucket say:

=== RULES ===
{RULES}
=== END RULES ===

Load the task by those rules (the files are under .claude/scratch/{SLUG}/). Then answer the
questions below from what you find in this project's files, looking further only where the
rules allow. If you cannot find it, answer exactly "UNKNOWN" - never guess. Keep answers short.
Budget: after about 40 tool calls stop searching and answer with what you have (UNKNOWN for the
rest). Finish with ONLY this JSON as your final message, complete or not:
{"answers":[{"id":"P1","answer":"..."}]}

=== QUESTIONS ===
{Q}
"""


def chain_dir(chain, *parts):
    return os.path.join(OUT, chain, *parts)


def bucket_src(root, slug):
    for base in (os.path.join(root, ".claude", "scratch"), os.path.join(root, ".claude", "scratch", "_closed")):
        if os.path.isdir(os.path.join(base, slug)):
            return os.path.join(base, slug)
    raise SystemExit(f"no bucket {slug} under {root}")


def sessions(root, slug):
    """[(joined, sid, transcript)] of the sessions on disk that worked ON `slug` - wrote its
    STATE, FINDINGS or DECISIONS, or read it and wrote no other bucket (kit_chain.owned) - oldest
    first. Round 2 (2026-10-09) counted any touch: a session that only read this task's STATE.md
    while handing off ANOTHER task became "the last session", and the old arm was given its
    digest, which neither kit puts in this bucket."""
    folder = kc.project_folder(root)
    out = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(folder, name)
        info = kc.scan(path, name[:-6])
        v = (info or {}).get("buckets", {}).get(slug)
        if v and slug in kc.owned(info, root):
            out.append((v["joined"], name[:-6], path))
    return sorted(out)


def rules(ref=None):
    """The `Continue a bucket` step 1 text (and the bucket layout) of task.md, at a git ref or now."""
    if ref:
        text = subprocess.run(["git", "show", f"{ref}:core/commands/task.md"], cwd=REPO,
                              capture_output=True).stdout.decode("utf-8")
    else:
        text = open(os.path.join(REPO, "core", "commands", "task.md"), encoding="utf-8").read()
    layout = re.search(r"```\n\.claude/scratch/<slug>/.*?```", text, re.S).group(0)
    step = re.search(r"## 5\. Continue a bucket.*?(?=\n2\. \*\*Verify)", text, re.S).group(0)
    return layout + "\n\n" + step


def copy_bucket(src, dst, notes_only=True):
    os.makedirs(dst, exist_ok=True)
    for f in ("STATE.md", "FINDINGS.md", "DECISIONS.md"):
        if os.path.isfile(os.path.join(src, f)):
            shutil.copy2(os.path.join(src, f), os.path.join(dst, f))


def prep(chain, arms=("new", "old")):
    """Both sandboxes, or only `arms`: round 4 (2026-10-10) rebuilt the new arm alone with the
    fixed kit and kept round 3's old arm, its answers and grades as the baseline."""
    root, slug, other = CHAINS[chain]
    ss = sessions(root, slug)
    so = sessions(root, other)
    if len(ss) < 4:
        return f"{chain}: only {len(ss)} sessions on disk, skipped"
    for arm in arms:
        shutil.rmtree(chain_dir(chain, arm), ignore_errors=True)
    for arm in arms:
        sb = chain_dir(chain, arm)
        os.makedirs(os.path.join(sb, ".claude", "scratch"))
        copy_bucket(bucket_src(root, slug), os.path.join(sb, ".claude", "scratch", slug))
        copy_bucket(bucket_src(root, other), os.path.join(sb, ".claude", "scratch", other))
        with open(os.path.join(sb, "CLAUDE.md"), "w", encoding="utf-8") as f:
            f.write("# sandbox\n")
    # new: every session's records, in both buckets, by the shipped code
    nb = chain_dir(chain, "new")
    if "new" in arms:
        for _, sid, path in sorted(set(ss) | set(so)):
            kc.finish(path, sid, nb, counts=False)
    # old: the newest 5 digests per bucket, nothing else
    for s, lst in ((slug, ss), (other, so)) if "old" in arms else ():
        folder = os.path.join(chain_dir(chain, "old"), ".claude", "scratch", s, "digests")
        for _, sid, path in lst[-5:]:
            kd.write(path, os.path.join(folder, sid + ".md"), {"session": sid}, kd.cap_tokens(0, 1_000_000))
    # material for the probe writer
    recs = []
    for i, (_, sid, path) in enumerate(ss[:-1], 1):
        recs.append(f"=== SESSION S{i} ({sid}) ===\n" + kd.render(kd.extract(path), {"session": sid}, PROBE_CAP))
    bucket = os.path.join(nb, ".claude", "scratch", slug)
    handoff = "\n\n".join(open(os.path.join(bucket, f), encoding="utf-8").read()
                          for f in ("STATE.md", "DECISIONS.md", "FINDINGS.md") if os.path.isfile(os.path.join(bucket, f)))
    last = kd.render(kd.extract(ss[-1][2]), {"session": ss[-1][1]}, PROBE_CAP)
    meta = {"sessions": [s for _, s, _ in ss], "n": len(ss), "distractor_sessions": len(so),
            "sessions_md_tokens": len(open(os.path.join(bucket, "SESSIONS.md"), encoding="utf-8").read()) // 4
            if os.path.isfile(os.path.join(bucket, "SESSIONS.md")) else 0}
    if "old" not in arms:  # the probes stay as they were; only say whether the material moved
        with open(chain_dir(chain, "meta-new.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=1)
        return f"{chain}: new arm rebuilt, {len(ss)} sessions, SESSIONS.md ~{meta['sessions_md_tokens']} tok"
    with open(chain_dir(chain, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    with open(chain_dir(chain, "probe_input.md"), "w", encoding="utf-8") as f:
        f.write(PROBE_PROMPT.replace("{N1}", str(len(ss) - 1)).replace("{N}", str(len(ss)))
                .replace("{RECORDS}", "\n\n".join(recs)).replace("{HANDOFF}", handoff).replace("{LAST}", last))
    old_n = len(os.listdir(os.path.join(chain_dir(chain, "old"), ".claude", "scratch", slug, "digests"))) - 1
    return (f"{chain}: {len(ss)} sessions; new arm all records + SESSIONS.md "
            f"(~{meta['sessions_md_tokens']} tok); old arm {old_n} digests; probe input "
            f"~{os.path.getsize(chain_dir(chain, 'probe_input.md')) // 4} tok")


def probes(chain):
    out = ab.claude(open(chain_dir(chain, "probe_input.md"), encoding="utf-8").read())
    ps = ab.parse_list(out["text"], "probes")
    with open(chain_dir(chain, "probes.json"), "w", encoding="utf-8") as f:
        json.dump({"probes": ps, "usage": {k: out.get(k) for k in ("in", "out", "cost")}}, f, indent=1, ensure_ascii=False)
    return f"{chain}: {len(ps)} probes ({sum(1 for p in ps if p.get('kind') == 'earlier')} earlier)"


def memory_index(root):
    """The project's auto-memory index, MEMORY.md, as Claude Code loads it at every session start
    (its first 200 lines / 25 KB); "" when the project has none."""
    path = os.path.join(kc.project_folder(root), "memory", "MEMORY.md")
    try:
        with open(path, encoding="utf-8") as f:
            return "".join(f.readlines()[:200])[:25_000]
    except OSError:
        return ""


def reader(chain, arm, k, mem=False):
    """One reader run. mem=True (round 5, 2026-10-10) also hands it the project's MEMORY.md index,
    which every real session starts with and the sandbox otherwise lacks; saved as `<arm>m-<k>`."""
    root, slug, other = CHAINS[chain]
    dst = chain_dir(chain, "answers", f"{arm}{'m' if mem else ''}-{k}.json")
    if os.path.exists(dst):
        return f"{chain}/{arm}-{k}: cached"
    ps = json.load(open(chain_dir(chain, "probes.json"), encoding="utf-8"))["probes"]
    q = "\n".join(f"{p['id']}: {p['question']}" for p in ps)
    prompt = (READER_PROMPT.replace("{SLUG}", slug).replace("{RULES}", rules(OLD_REF if arm == "old" else None))
              .replace("{Q}", q))
    if mem and memory_index(root):
        prompt = ("Claude Code loaded this project's auto memory index at session start (as it does in "
                  "every session):\n=== MEMORY.md ===\n" + memory_index(root) + "\n=== END MEMORY.md ===\n\n" + prompt)
    # --max-turns 60 ended 3 of 16 round-1 runs (both arms) after 71-89 tool calls with no final
    # JSON: they scored 0. Now 150, and the prompt asks for answers after ~40 calls.
    r = subprocess.run([EXE, "-p", "--safe-mode", "--tools", "Read,Grep,Glob", "--allowedTools", "Read,Grep,Glob",
                        "--no-session-persistence", "--model", MODEL, "--max-turns", "150",
                        "--output-format", "stream-json", "--verbose"],
                       input=prompt.encode("utf-8"), capture_output=True, timeout=3600,
                       cwd=chain_dir(chain, arm), env=dict(os.environ, MSYS_NO_PATHCONV="1"))
    calls, result, usage, cost = [], "", {}, None
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if o.get("type") == "assistant":
            for b in (o.get("message") or {}).get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    calls.append({"name": b.get("name"), "input": b.get("input")})
        elif o.get("type") == "result":
            result, usage, cost = str(o.get("result") or ""), o.get("usage") or {}, o.get("total_cost_usd")
    blob = json.dumps(calls)
    os.makedirs(chain_dir(chain, "answers"), exist_ok=True)
    rec = {"answers": ab.parse_list(result, "answers"), "calls": len(calls),
           "in": sum(int(usage.get(x) or 0) for x in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
           "out": int(usage.get("output_tokens") or 0), "cost": cost,
           "distractor": other in blob, "sessions_md": "SESSIONS.md" in blob,
           "state_snapshots": blob.count(".state.md"), "trail": calls}
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(rec, f, indent=1, ensure_ascii=False)
    return f"{chain}/{arm}-{k}: {len(rec['answers'])} answers, {rec['calls']} calls, in {rec['in']} tok"


def grade(chain):
    ps = {x["id"]: x for x in json.load(open(chain_dir(chain, "probes.json"), encoding="utf-8"))["probes"]}
    os.makedirs(chain_dir(chain, "grades"), exist_ok=True)
    done = []
    for fn in sorted(os.listdir(chain_dir(chain, "answers"))):
        dst = chain_dir(chain, "grades", fn)
        if os.path.exists(dst):
            continue
        ans = {a.get("id"): a.get("answer", "") for a in json.load(open(chain_dir(chain, "answers", fn), encoding="utf-8"))["answers"]
               if isinstance(a, dict)}
        ids = list(ps)
        random.Random(fn).shuffle(ids)
        items = "\n\n".join(f"id: {i}\nquestion: {ps[i]['question']}\ngold: {ps[i]['gold']}\nanswer: {ans.get(i, 'UNKNOWN')}" for i in ids)
        out = ab.claude(ab.GRADE_PROMPT.replace("{ITEMS}", items))
        with open(dst, "w", encoding="utf-8") as f:
            json.dump({"grades": ab.parse_list(out["text"], "grades")}, f, indent=1)
        done.append(fn)
    return f"{chain}: graded {len(done)}"


def report(chains):
    rows = {}
    for chain in chains:
        if not os.path.isfile(chain_dir(chain, "probes.json")) or not os.path.isdir(chain_dir(chain, "grades")):
            continue
        ps = {x["id"]: x for x in json.load(open(chain_dir(chain, "probes.json"), encoding="utf-8"))["probes"]}
        for fn in sorted(os.listdir(chain_dir(chain, "grades"))):
            arm = fn.rsplit("-", 1)[0]
            g = {x.get("id"): x for x in json.load(open(chain_dir(chain, "grades", fn), encoding="utf-8"))["grades"] if isinstance(x, dict)}
            a = json.load(open(chain_dir(chain, "answers", fn), encoding="utf-8"))
            r = rows.setdefault(arm, {"s": {"earlier": [0.0, 0], "any": [0.0, 0]}, "wrong": 0, "in": [], "cost": [],
                                      "calls": [], "distractor": 0, "runs": 0, "chain": {}})
            r["runs"] += 1
            r["in"].append(a.get("in") or 0)
            r["cost"].append(a.get("cost") or 0)
            r["calls"].append(a.get("calls") or 0)
            r["distractor"] += bool(a.get("distractor"))
            cs = r["chain"].setdefault(chain, [0.0, 0])
            for pid, p in ps.items():
                s = float((g.get(pid) or {}).get("score") or 0)
                kind = "earlier" if p.get("kind") == "earlier" else "any"
                r["s"][kind][0] += s
                r["s"][kind][1] += 1
                r["wrong"] += bool((g.get(pid) or {}).get("wrong"))
                cs[0] += s
                cs[1] += 1

    def pct(x):
        return f"{x[0] * 100 / max(x[1], 1):5.1f}%"
    print(f"{'arm':5} {'earlier':>8} {'any':>8} {'all':>8} {'wrong':>5} {'avg in tok':>10} {'avg $':>7} {'calls':>6} {'distractor':>10}  "
          + " ".join(f"{c:>8}" for c in chains))
    for arm in ("old", "new", "oldm", "newm"):  # m = with the project's MEMORY.md index (round 5)
        r = rows.get(arm)
        if not r:
            continue
        tot = [r["s"]["earlier"][0] + r["s"]["any"][0], r["s"]["earlier"][1] + r["s"]["any"][1]]
        per = " ".join(f"{pct(r['chain'].get(c, [0, 0])):>8}" for c in chains)
        print(f"{arm:5} {pct(r['s']['earlier']):>8} {pct(r['s']['any']):>8} {pct(tot):>8} {r['wrong']:>5} "
              f"{sum(r['in']) // max(r['runs'], 1):>10} {sum(r['cost']) / max(r['runs'], 1):>7.2f} "
              f"{sum(r['calls']) / max(r['runs'], 1):>6.1f} {r['distractor']:>4}/{r['runs']:<5}  {per}")
    for chain in chains:
        if os.path.isfile(chain_dir(chain, "meta.json")):
            m = json.load(open(chain_dir(chain, "meta.json"), encoding="utf-8"))
            print(f"  {chain}: {m['n']} sessions, SESSIONS.md ~{m['sessions_md_tokens']} tokens on the default path")


def main(argv):
    cmd = argv[0]
    samples = int(argv[argv.index("--samples") + 1]) if "--samples" in argv else 2
    arms = tuple(argv[argv.index("--arms") + 1].split(",")) if "--arms" in argv else ("old", "new")
    chains = [c for c in argv[1:] if c in CHAINS] or list(CHAINS)
    if cmd == "report":
        return report(chains)
    if cmd == "read":
        mem = "--memory" in argv
        jobs = [(c, arm, k, mem) for c in chains for arm in arms for k in range(samples)]
        with cf.ThreadPoolExecutor(4) as ex:
            for line in ex.map(lambda j: reader(*j), jobs):
                print(line, flush=True)
        return
    if cmd == "prep":
        with cf.ThreadPoolExecutor(4) as ex:
            for line in ex.map(lambda c: prep(c, arms), chains):
                print(line, flush=True)
        return
    fn = {"probes": probes, "grade": grade}[cmd]
    with cf.ThreadPoolExecutor(4) as ex:
        for line in ex.map(fn, chains):
            print(line, flush=True)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1:])
