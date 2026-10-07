"""Handoff A/B: how much of session A a cold reader can answer from each handoff arm.

  python ab.py probes <chain>...        Opus writes ~20 probes per chain from raw_A.md (+ B excerpt)
  python ab.py read   <chain>... [--samples 2] [--arms a,b]
  python ab.py grade  <chain>...        blind: the grader never sees an arm's name
  python ab.py report <chain>...

Materials come from prep.py and compact_fork.py in bench/results/handoff-ab/<chain>/.
Every model call is `claude -p --safe-mode --tools "" --no-session-persistence` on the bundled
binary: no tools, no hooks, no CLAUDE.md, so a reader knows only its note.
"""
import concurrent.futures as cf
import json
import os
import random
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "results", "handoff-ab")
EXE = os.environ.get("CLAUDE_CODE_EXECPATH") or "claude"
MODEL = os.environ.get("AB_MODEL", "claude-opus-5-5")
ARMS = {
    "none": [],
    "compact": ["compact.md"],
    "kit_now": ["kit_now.md"],
    "digest_lean": ["digest_lean.md"],
    "digest_full": ["digest_full.md"],
    "kit_new_lean": ["kit_now.md", "digest_lean.md"],
    "kit_new": ["kit_now.md", "digest_full.md"],
}
CATS = ("user_instruction", "decision", "state_done", "literal", "trap", "next", "why")

PROBE_PROMPT = """You are building a test of SESSION HANDOFF quality. Below is the full record of a
Claude Code working session ("session A"), with tool outputs, followed by an excerpt of the session
that resumed it ("session B").

Write exactly 20 probe questions that a successor session must be able to answer to continue A's
work correctly, without re-asking the user and without redoing work. Every answer must be stated
or plainly shown in session A (never only in B). Use B's excerpt only to see what turned out to
matter. Spread them: 4 user_instruction (what the user asked, decided, preferred, forbade, or how
they want results reported - their own words where they matter), 3 decision (a choice made and
its reason), 3 state_done (what is finished and how it was verified, with the numbers), 4 literal
(an exact path, command, ID, version, count or value), 2 trap (something that failed or must not
be repeated, as it was seen), 2 next (the exact next step or an open question), 2 why (a user
worry, requirement or reason behind the work).

Rules: one fact per question; answers short (a phrase, a number, a path) and checkable; no
trivia that only mattered inside A; prefer facts from the LATER part of A where the work stood at
the end; never ask about B. Output ONLY JSON:
{"probes":[{"id":"P1","category":"...","question":"...","gold":"...","source":"L<line>"}]}

=== SESSION A ===
{A}

=== SESSION B (excerpt, context only) ===
{B}
"""

READ_PROMPT = """You are resuming someone else's work in a new session. All you have about the
earlier session is the HANDOFF MATERIAL below (it may be empty). Answer every question from that
material alone. If the material does not say, answer exactly "UNKNOWN" - do not guess, and do
not use general knowledge to fill a gap. Keep each answer short.

Output ONLY JSON: {"answers":[{"id":"P1","answer":"..."}]}

=== HANDOFF MATERIAL ===
{NOTE}
=== END ===

=== QUESTIONS ===
{Q}
"""

GRADE_PROMPT = """Grade answers against gold answers. For each item: score 1 if the answer gives
the gold fact (wording may differ; an exact literal - path, number, command, ID - must match
exactly), 0.5 if it is partly right or right but missing a required part, 0 if it is UNKNOWN,
empty or wrong. Also set "wrong": true when the answer states something that CONTRADICTS the
gold (a confident wrong answer), false otherwise (UNKNOWN is never wrong).

Output ONLY JSON: {"grades":[{"id":"P1","score":1,"wrong":false}]}

=== ITEMS ===
{ITEMS}
"""


def claude(prompt, timeout=1800):
    r = subprocess.run([EXE, "-p", "--safe-mode", "--tools", "", "--no-session-persistence",
                        "--model", MODEL, "--output-format", "json"],
                       input=prompt.encode("utf-8"), capture_output=True, timeout=timeout,
                       env=dict(os.environ, MSYS_NO_PATHCONV="1"))
    try:
        out = json.loads(r.stdout.decode("utf-8"))
    except ValueError:
        return {"error": r.stderr.decode("utf-8", "replace")[-500:], "text": ""}
    u = out.get("usage") or {}
    return {"text": out.get("result", ""), "in": sum(int(u.get(k) or 0) for k in (
        "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")),
            "out": int(u.get("output_tokens") or 0), "cost": out.get("total_cost_usd")}


def parse_list(text, key):
    """The list under `key` from a model's JSON, tolerant of prose around it and of one bad
    object (the 09-29 run lost a whole arm to `{"id": "P2": ...}`)."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0)).get(key) or []
        except ValueError:
            pass
    items = []
    for obj in re.findall(r"\{[^{}]*\}", text):
        try:
            items.append(json.loads(obj))
        except ValueError:
            continue
    return items


def p(chain, *parts):
    return os.path.join(ROOT, chain, *parts)


def read_file(chain, name):
    try:
        with open(p(chain, name), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def cmd_probes(chains):
    def one(chain):
        out = claude(PROBE_PROMPT.replace("{A}", read_file(chain, "raw_A.md"))
                     .replace("{B}", read_file(chain, "b_excerpt.md") or ""))
        probes = parse_list(out["text"], "probes")
        with open(p(chain, "probes.json"), "w", encoding="utf-8") as f:
            json.dump({"probes": probes, "usage": {k: out.get(k) for k in ("in", "out", "cost")}},
                      f, indent=1, ensure_ascii=False)
        return f"{chain}: {len(probes)} probes, in {out.get('in')} tok"
    with cf.ThreadPoolExecutor(4) as ex:
        for r in ex.map(one, chains):
            print(r)


def note_for(chain, arm):
    texts = [read_file(chain, f) for f in ARMS[arm]]
    if any(t is None for t in texts):
        return None
    return "\n\n---\n\n".join(texts)


def cmd_read(chains, samples, arms):
    jobs = []
    for chain in chains:
        probes = json.load(open(p(chain, "probes.json"), encoding="utf-8"))["probes"]
        q = "\n".join(f"{x['id']}: {x['question']}" for x in probes)
        os.makedirs(p(chain, "answers"), exist_ok=True)
        for arm in arms:
            note = note_for(chain, arm)
            if note is None:
                print(f"{chain}/{arm}: material missing, skipped")
                continue
            for k in range(samples):
                dst = p(chain, "answers", f"{arm}-{k}.json")
                if not os.path.exists(dst):
                    jobs.append((chain, arm, k, READ_PROMPT.replace("{NOTE}", note).replace("{Q}", q), dst))

    def one(job):
        chain, arm, k, prompt, dst = job
        out = claude(prompt)
        ans = parse_list(out["text"], "answers")
        with open(dst, "w", encoding="utf-8") as f:
            json.dump({"answers": ans, "in": out.get("in"), "out": out.get("out"),
                       "error": out.get("error")}, f, indent=1, ensure_ascii=False)
        return f"{chain}/{arm}-{k}: {len(ans)} answers, in {out.get('in')} tok"
    with cf.ThreadPoolExecutor(6) as ex:
        for r in ex.map(one, jobs):
            print(r, flush=True)


def cmd_grade(chains):
    jobs = []
    for chain in chains:
        probes = {x["id"]: x for x in json.load(open(p(chain, "probes.json"), encoding="utf-8"))["probes"]}
        os.makedirs(p(chain, "grades"), exist_ok=True)
        for fn in sorted(os.listdir(p(chain, "answers"))):
            dst = p(chain, "grades", fn)
            if os.path.exists(dst):
                continue
            ans = {a.get("id"): a.get("answer", "") for a in
                   json.load(open(p(chain, "answers", fn), encoding="utf-8"))["answers"] if isinstance(a, dict)}
            ids = list(probes)
            random.Random(fn).shuffle(ids)  # order differs per file; the arm name is never sent
            items = "\n\n".join(f"id: {i}\nquestion: {probes[i]['question']}\ngold: {probes[i]['gold']}\n"
                                f"answer: {ans.get(i, 'UNKNOWN')}" for i in ids)
            jobs.append((chain, fn, GRADE_PROMPT.replace("{ITEMS}", items), dst))

    def one(job):
        chain, fn, prompt, dst = job
        out = claude(prompt)
        g = parse_list(out["text"], "grades")
        with open(dst, "w", encoding="utf-8") as f:
            json.dump({"grades": g}, f, indent=1)
        return f"{chain}/{fn}: {len(g)} grades"
    with cf.ThreadPoolExecutor(6) as ex:
        for r in ex.map(one, jobs):
            print(r, flush=True)


def cmd_report(chains):
    rows = {}
    for chain in chains:
        probes = {x["id"]: x for x in json.load(open(p(chain, "probes.json"), encoding="utf-8"))["probes"]}
        for fn in sorted(os.listdir(p(chain, "grades"))):
            arm = fn.rsplit("-", 1)[0]
            g = {x.get("id"): x for x in json.load(open(p(chain, "grades", fn), encoding="utf-8"))["grades"]
                 if isinstance(x, dict)}
            a = json.load(open(p(chain, "answers", fn), encoding="utf-8"))
            r = rows.setdefault(arm, {"score": 0.0, "n": 0, "wrong": 0, "tok": [], "cat": {}, "chain": {}})
            note = note_for(chain, arm) or ""
            r["tok"].append(len(note) // 4)
            cs = r["chain"].setdefault(chain, [0.0, 0])
            for pid, pr in probes.items():
                s = float((g.get(pid) or {}).get("score") or 0)
                r["score"] += s
                r["n"] += 1
                r["wrong"] += bool((g.get(pid) or {}).get("wrong"))
                c = r["cat"].setdefault(pr.get("category", "?"), [0.0, 0])
                c[0] += s
                c[1] += 1
                cs[0] += s
                cs[1] += 1
    order = ["none", "compact", "kit_now", "digest_lean", "digest_full", "kit_new_lean", "kit_new"]
    print(f"{'arm':14} {'score':>6} {'wrong':>5} {'~tok':>7}  " + " ".join(f"{c[:9]:>9}" for c in CATS)
          + "  " + " ".join(f"{c[:9]:>9}" for c in chains))
    for arm in [x for x in order if x in rows]:
        r = rows[arm]
        cat = " ".join(f"{(r['cat'].get(c, [0, 0])[0] * 100 / max(r['cat'].get(c, [0, 1])[1], 1)):>8.0f}%"
                       for c in CATS)
        per = " ".join(f"{(r['chain'].get(c, [0, 0])[0] * 100 / max(r['chain'].get(c, [0, 1])[1], 1)):>8.0f}%"
                       for c in chains)
        print(f"{arm:14} {r['score'] * 100 / max(r['n'], 1):>5.1f}% {r['wrong']:>5} "
              f"{sum(r['tok']) // max(len(r['tok']), 1):>7}  {cat}  {per}")


def main(argv):
    cmd, rest = argv[0], argv[1:]
    samples = 2
    arms = list(ARMS)
    chains = []
    i = 0
    while i < len(rest):
        if rest[i] == "--samples":
            samples = int(rest[i + 1])
            i += 2
        elif rest[i] == "--arms":
            arms = rest[i + 1].split(",")
            i += 2
        else:
            chains.append(rest[i])
            i += 1
    {"probes": lambda: cmd_probes(chains), "read": lambda: cmd_read(chains, samples, arms),
     "grade": lambda: cmd_grade(chains), "report": lambda: cmd_report(chains)}[cmd]()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1:])
